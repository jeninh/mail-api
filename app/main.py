import hashlib
import hmac
import html
import logging
import random
import secrets
import string
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.airtable_client import airtable_client
from app.background_jobs import check_all_pending_letters, start_scheduler, stop_scheduler
from app.config import get_settings
from app.cost_calculator import (
    CostCalculationError,
    ParcelQuoteRequired,
    calculate_cost,
    cents_to_usd,
    get_stamp_region,
)
from app.database import get_db, init_db
from app.models import Event, Letter, LetterStatus, MailType, Order, OrderStatus
from app.rubber_stamp_formatter import format_rubber_stamps
from app.schemas import (
    CostCalculatorRequest,
    CostCalculatorResponse,
    ErrorResponse,
    FinancialSummaryResponse,
    LetterCreate,
    LetterResponse,
    MarkPaidResponse,
    OrderCreate,
    OrderResponse,
    OrderStatusResponse,
    StampCounts,
    StatusCheckResponse,
    UnpaidEvent,
)
from app.security import hash_api_key
from app.slack_bot import slack_bot
from app.slack_socket_handler import start_socket_mode, stop_socket_mode
from app.theseus_client import TheseusAPIError, theseus_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()

# Rate limiter for public endpoints (no API key required)
limiter = Limiter(key_func=get_remote_address)

# Rate limiter for auth attempts (stricter limits)
auth_limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await slack_bot.send_server_lifecycle_notification("database_connected")

    start_scheduler()
    await slack_bot.send_server_lifecycle_notification("scheduler_started")

    await start_socket_mode()
    await slack_bot.send_server_lifecycle_notification("socket_mode_connected")

    await slack_bot.send_server_lifecycle_notification("startup", f"API v{app.version} running on {settings.api_host}:{settings.api_port}")
    logger.info("Application started")

    yield

    await slack_bot.send_server_lifecycle_notification("shutdown", "Graceful shutdown initiated")

    await stop_socket_mode()
    await slack_bot.send_server_lifecycle_notification("socket_mode_disconnected")

    stop_scheduler()
    await slack_bot.send_server_lifecycle_notification("scheduler_stopped")

    logger.info("Application stopped")


app = FastAPI(
    title="Theseus Mail Wrapper API",
    description="A wrapper API for Hack Club's Theseus mail system",
    version="1.0.0",
    lifespan=lifespan
)

app.state.limiter = limiter
app.state.auth_limiter = auth_limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please try again later."}
    )


from fastapi.exceptions import RequestValidationError


@app.exception_handler(RequestValidationError)
async def pii_safe_validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Custom validation error handler that does NOT echo input values.
    This prevents PII (names, addresses, emails) from leaking in 422 error responses.
    """
    safe_errors = []
    for error in exc.errors():
        safe_errors.append({
            "loc": error.get("loc"),
            "msg": error.get("msg"),
            "type": error.get("type")
        })

    return JSONResponse(
        status_code=422,
        content={"detail": safe_errors}
    )


@app.exception_handler(Exception)
async def pii_safe_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler that prevents PII from leaking in 500 error responses.
    Logs the full exception internally but returns a generic message to clients.
    Also sends error notification to Slack with the error ID.
    """
    error_id = str(uuid.uuid4())[:8]

    logger.error(
        f"Unhandled exception [error_id={error_id}] on {request.method} {request.url.path}: "
        f"{type(exc).__name__}: {exc}",
        exc_info=True
    )

    try:
        await slack_bot.send_error_notification(
            event_name=f"Server Error [{error_id}]",
            error_message=f"{type(exc).__name__}: {exc}",
            request_summary=f"{request.method} {request.url.path}"
        )
    except Exception as slack_error:
        logger.error(f"Failed to send Slack error notification: {slack_error}")

    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred. Please try again later.",
            "error_id": error_id
        }
    )


@auth_limiter.limit("10/minute")
async def verify_event_api_key(
    request: Request,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db)
) -> Event:
    """Verifies the event API key and returns the event."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    api_key = authorization.replace("Bearer ", "")
    api_key_hashed = hash_api_key(api_key)

    stmt = select(Event).where(Event.api_key_hash == api_key_hashed)
    result = await db.execute(stmt)
    event = result.scalar_one_or_none()

    if not event:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return event


@auth_limiter.limit("10/minute")
async def verify_admin_api_key(request: Request, authorization: str = Header(...)) -> bool:
    """Verifies the admin API key."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    api_key = authorization.replace("Bearer ", "")

    if not secrets.compare_digest(api_key, settings.admin_api_key):
        raise HTTPException(status_code=401, detail="Invalid admin API key")

    return True


async def verify_slack_signature(
    request: Request,
    x_slack_signature: str = Header(None, alias="X-Slack-Signature"),
    x_slack_request_timestamp: str = Header(None, alias="X-Slack-Request-Timestamp")
) -> bytes:
    """
    Verifies that the request comes from Slack using signature verification.
    Returns the raw request body for further processing.
    """
    if not x_slack_signature or not x_slack_request_timestamp:
        raise HTTPException(status_code=401, detail="Missing Slack signature headers")

    try:
        timestamp = int(x_slack_request_timestamp)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Slack timestamp")

    if abs(time.time() - timestamp) > 60 * 5:
        raise HTTPException(status_code=401, detail="Stale Slack request")

    body = await request.body()

    basestring = f"v0:{x_slack_request_timestamp}:{body.decode()}"
    computed_signature = "v0=" + hmac.new(
        settings.slack_signing_secret.encode(),
        basestring.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_signature, x_slack_signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    return body


@app.post("/api/v1/letters", response_model=LetterResponse, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def create_letter(
    request: LetterCreate,
    event: Event = Depends(verify_event_api_key),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new letter in the Theseus system.

    Requires a valid event API key in the Authorization header.
    """
    try:
        if request.mail_type == MailType.BUBBLE_PACKET and request.weight_grams and request.weight_grams > 500:
            raise HTTPException(
                status_code=400,
                detail="Weight exceeds 500g for bubble packets. A parcel is needed. Please DM @jenin on Slack for rates."
            )

        cost_cents = calculate_cost(
            mail_type=request.mail_type,
            country=request.country,
            weight_grams=request.weight_grams
        )

    except CostCalculationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ParcelQuoteRequired:
        cost_cents = 0

    formatted_stamps = format_rubber_stamps(request.rubber_stamps)

    address = {
        "first_name": request.first_name,
        "last_name": request.last_name,
        "line_1": request.address_line_1,
        "line_2": request.address_line_2,
        "city": request.city,
        "state": request.state,
        "postal_code": request.postal_code,
        "country": request.country
    }

    try:
        theseus_response = await theseus_client.create_letter(
            queue_name=event.theseus_queue,
            address=address,
            rubber_stamps=formatted_stamps,
            recipient_email=request.recipient_email,
            notes=request.notes
        )
    except TheseusAPIError as e:
        logger.error(f"Theseus API error for event {event.name}: {e.message}")
        await slack_bot.send_error_notification(
            event_name=event.name,
            error_message=str(e),
            request_summary=f"Recipient: {request.first_name}, {request.country}"
        )
        raise HTTPException(
            status_code=502,
            detail="Mail service temporarily unavailable. Please DM @hermes on Slack."
        )

    letter_id = theseus_response.get("id")

    letter = Letter(
        letter_id=letter_id,
        event_id=event.id,
        first_name=request.first_name,
        last_name=request.last_name,
        address_line_1=request.address_line_1,
        address_line_2=request.address_line_2,
        city=request.city,
        state=request.state,
        postal_code=request.postal_code,
        country=request.country,
        recipient_email=request.recipient_email,
        mail_type=request.mail_type,
        weight_grams=request.weight_grams,
        rubber_stamps_raw=request.rubber_stamps,
        rubber_stamps_formatted=formatted_stamps,
        notes=request.notes,
        cost_cents=cost_cents,
        status=LetterStatus.QUEUED
    )

    db.add(letter)

    # Use atomic SQL update to prevent race conditions
    await db.execute(
        update(Event)
        .where(Event.id == event.id)
        .values(
            letter_count=Event.letter_count + 1,
            balance_due_cents=Event.balance_due_cents + cost_cents
        )
    )

    await db.flush()

    try:
        message_ts, channel_id = await slack_bot.send_letter_created_notification(
            event_name=event.name,
            queue_name=event.theseus_queue,
            recipient_name=f"{request.first_name} {request.last_name}",
            country=request.country,
            rubber_stamps_raw=request.rubber_stamps,
            cost_cents=cost_cents,
            notes=request.notes,
            letter_id=letter_id
        )
        letter.slack_message_ts = message_ts
        letter.slack_channel_id = channel_id
    except Exception as e:
        logger.error(f"Failed to send Slack notification: {e}")

    if request.mail_type == MailType.PARCEL:
        await slack_bot.send_parcel_quote_request(
            event_name=event.name,
            weight_grams=request.weight_grams,
            country=request.country,
            recipient_name=f"{request.first_name} {request.last_name}",
            rubber_stamps_raw=request.rubber_stamps,
            letter_id=letter_id
        )

    try:
        await update_financial_canvas(db)
    except Exception as e:
        logger.error(f"Failed to update financial canvas: {e}")

    await db.commit()

    try:
        full_address = f"{request.first_name} {request.last_name}<br>{request.address_line_1}"
        if request.address_line_2:
            full_address += f"<br>{request.address_line_2}"
        full_address += f"<br>{request.city}, {request.state}, {request.postal_code}<br>{request.country}"
        if request.recipient_email:
            full_address += f"<br>{request.recipient_email}"

        await airtable_client.create_record(
            first_name=request.first_name,
            last_name=request.last_name,
            email=request.recipient_email or "",
            email_reason="Letter",
            record_id=letter_id,
            ysws=event.name,
            contains=request.rubber_stamps,
            full_address=full_address,
        )
    except Exception as e:
        logger.error(f"Failed to create Airtable record for letter: {e}")

    return LetterResponse(
        letter_id=letter_id,
        cost_usd=cents_to_usd(cost_cents),
        formatted_rubber_stamps=formatted_stamps,
        status=LetterStatus.QUEUED,
        theseus_url=theseus_client.get_public_letter_url(letter_id),
        email_sent=True
    )


@app.post("/admin/events/{event_id}/mark-paid", response_model=MarkPaidResponse)
async def mark_event_paid(
    event_id: int,
    _: bool = Depends(verify_admin_api_key),
    db: AsyncSession = Depends(get_db)
):
    """Mark an event as paid and reset its balance."""
    stmt = select(Event).where(Event.id == event_id)
    result = await db.execute(stmt)
    event = result.scalar_one_or_none()

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    previous_balance = event.balance_due_cents
    event.balance_due_cents = 0
    event.is_paid = True

    await db.commit()

    try:
        await update_financial_canvas(db)
    except Exception as e:
        logger.error(f"Failed to update financial canvas: {e}")

    return MarkPaidResponse(
        event_id=event.id,
        event_name=event.name,
        previous_balance_cents=previous_balance,
        new_balance_cents=0,
        is_paid=True
    )


@app.get("/admin/financial-summary", response_model=FinancialSummaryResponse)
async def get_financial_summary(
    _: bool = Depends(verify_admin_api_key),
    db: AsyncSession = Depends(get_db)
):
    """Get a financial summary of all unpaid events."""
    stmt = select(Event).where(Event.balance_due_cents > 0)
    result = await db.execute(stmt)
    events = result.scalars().all()

    unpaid_events = []
    total_due_cents = 0
    total_ca = 0
    total_us = 0
    total_int = 0

    for event in events:
        last_letter_stmt = select(func.max(Letter.created_at)).where(Letter.event_id == event.id)
        last_letter_result = await db.execute(last_letter_stmt)
        last_letter_at = last_letter_result.scalar()

        letters_stmt = select(Letter.country).where(Letter.event_id == event.id)
        letters_result = await db.execute(letters_stmt)
        countries = letters_result.scalars().all()

        ca_count = sum(1 for c in countries if get_stamp_region(c) == "CA")
        us_count = sum(1 for c in countries if get_stamp_region(c) == "US")
        int_count = sum(1 for c in countries if get_stamp_region(c) == "INT")

        unpaid_events.append(UnpaidEvent(
            event_id=event.id,
            event_name=event.name,
            balance_due_usd=cents_to_usd(event.balance_due_cents),
            letter_count=event.letter_count,
            stamps=StampCounts(canada=ca_count, us=us_count, international=int_count),
            last_letter_at=last_letter_at
        ))
        total_due_cents += event.balance_due_cents
        total_ca += ca_count
        total_us += us_count
        total_int += int_count

    return FinancialSummaryResponse(
        unpaid_events=unpaid_events,
        total_due_usd=cents_to_usd(total_due_cents),
        total_stamps=StampCounts(canada=total_ca, us=total_us, international=total_int)
    )


@app.post("/admin/check-letter-status", response_model=StatusCheckResponse)
async def manual_status_check(_: bool = Depends(verify_admin_api_key)):
    """Manually trigger a status check for all pending letters."""
    result = await check_all_pending_letters()
    return StatusCheckResponse(**result)


@app.post("/api/v1/calculate-cost", response_model=CostCalculatorResponse)
@limiter.limit("30/minute")
async def calculate_shipping_cost(request: Request, body: CostCalculatorRequest):
    """Calculate shipping cost for a given mail type and destination."""
    try:
        cost_cents = calculate_cost(
            mail_type=body.mail_type,
            country=body.country,
            weight_grams=body.weight_grams
        )
        return CostCalculatorResponse(
            cost_cents=cost_cents,
            cost_usd=cents_to_usd(cost_cents)
        )
    except CostCalculationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ParcelQuoteRequired:
        return CostCalculatorResponse(
            cost_cents=0,
            cost_usd=0,
            message="Parcel requires custom quote. Please DM @jenin on Slack."
        )


def generate_order_id() -> str:
    """Generate a random 7-character alphanumeric order ID."""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=7))


def get_order_status_url(order_id: str) -> str:
    """Get the public status URL for an order."""
    return f"https://fulfillment.hackclub.com/odr!{order_id}"


def get_404_html(title: str = "Page Not Found", message: str = "The page you're looking for doesn't exist.") -> str:
    """Generate a styled 404 HTML page matching the odr! page style."""
    return f"""
    <!DOCTYPE html>
    <html lang="en" data-theme="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta name="color-scheme" content="dark">
        <title>404 - {title}</title>
        <link rel="stylesheet" href="https://css.hackclub.com/theme.css">
        <style>
            :root {{
                --bg: #121217;
                --card-bg: #1e1e24;
                --red: #ec3750;
            }}
            body {{
                background: var(--bg);
                color: #fff;
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 2rem;
            }}
            .eyebrow {{
                color: var(--red);
            }}
            .card {{
                background: var(--card-bg);
                border: 1px solid #333;
                padding: 2rem;
                border-radius: 0;
            }}
            .status-icon {{
                font-size: 3rem;
                margin-bottom: 0.5rem;
            }}
            h2 {{
                color: #fff;
            }}
            .caption {{
                color: #888;
            }}
            footer {{
                margin-top: 2rem;
                color: #666;
            }}
        </style>
    </head>
    <body>
        <main class="container narrow" style="text-align: center;">
            <p class="eyebrow">404</p>
            <div class="card sunken">
                <div class="status-icon">🔍</div>
                <h2>{title}</h2>
                <p class="caption">{message}</p>
            </div>
            <footer class="caption">Hermes Mail Service</footer>
        </main>
    </body>
    </html>
    """


@app.post("/api/v1/order", response_model=OrderResponse, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def create_order(
    request: OrderCreate,
    event: Event = Depends(verify_event_api_key),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new order request.

    Requires a valid event API key in the Authorization header.
    Orders are fulfilled by Hermes via local carrier and charged to the event's HCB.
    There is a $1 fee per item ordered.
    """
    order_id = generate_order_id()

    existing = await db.execute(select(Order).where(Order.order_id == order_id))
    while existing.scalar_one_or_none():
        order_id = generate_order_id()
        existing = await db.execute(select(Order).where(Order.order_id == order_id))

    status_url = get_order_status_url(order_id)

    order = Order(
        order_id=order_id,
        event_id=event.id,
        order_text=request.order_text,
        status=OrderStatus.PENDING
    )

    db.add(order)
    await db.flush()

    # Add $1 fee (100 cents) to event's balance
    await db.execute(
        update(Event)
        .where(Event.id == event.id)
        .values(balance_due_cents=Event.balance_due_cents + 100)
    )

    try:
        message_ts, channel_id = await slack_bot.send_order_notification(
            event_name=event.name,
            order_id=order_id,
            order_text=request.order_text,
            status_url=status_url,
            first_name=request.first_name,
            last_name=request.last_name,
            email=request.email,
            phone_number=request.phone_number,
            address_line_1=request.address_line_1,
            address_line_2=request.address_line_2,
            city=request.city,
            state=request.state,
            postal_code=request.postal_code,
            country=request.country,
            order_notes=request.order_notes
        )
        order.slack_message_ts = message_ts
        order.slack_channel_id = channel_id
    except Exception as e:
        logger.error(f"Failed to send Slack notification for order {order_id}: {e}")

    await db.commit()

    try:
        full_address = f"{request.first_name} {request.last_name}<br>{request.address_line_1}"
        if request.address_line_2:
            full_address += f"<br>{request.address_line_2}"
        full_address += f"<br>{request.city}, {request.state}, {request.postal_code}<br>{request.country}"
        if request.email:
            full_address += f"<br>{request.email}"

        await airtable_client.create_record(
            first_name=request.first_name,
            last_name=request.last_name,
            email=request.email or "",
            email_reason="Order",
            record_id=f"odr!{order_id}",
            ysws=event.name,
            contains=request.order_text,
            full_address=full_address,
        )
    except Exception as e:
        logger.error(f"Failed to create Airtable record for order: {e}")

    return OrderResponse(
        order_id=order_id,
        status=OrderStatus.PENDING,
        status_url=status_url,
        created_at=order.created_at,
        email_sent=True
    )


@app.get("/odr!{order_id}", response_class=HTMLResponse)
@limiter.limit("60/minute")
async def get_order_status_page(
    request: Request,
    order_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Public order status page.

    Shows pending/fulfilled status without any personal information.
    """
    stmt = select(Order).where(Order.order_id == order_id)
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order:
        return HTMLResponse(content=get_404_html("Order Not Found", "This order does not exist or the link is invalid."), status_code=404)

    escaped_order_id = html.escape(order_id)

    if order.status == OrderStatus.PENDING:
        status_html = """
        <div class="card sunken">
            <h2>Pending</h2>
            <p class="caption">Your order is being processed.</p>
        </div>
        """
    else:
        fulfillment_info = ""
        if order.fulfillment_note:
            escaped_note = html.escape(order.fulfillment_note)
            fulfillment_info = f'<p class="note">{escaped_note}</p>'
        if order.tracking_code:
            escaped_tracking = html.escape(order.tracking_code)
            fulfillment_info += f'<p class="tracking">Tracking: <code>{escaped_tracking}</code></p>'

        status_html = f"""
        <div class="card sunken">
            <div class="status-icon">✅</div>
            <h2>Fulfilled</h2>
            {fulfillment_info}
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Order {escaped_order_id}</title>
        <link rel="stylesheet" href="https://css.hackclub.com/theme.css">
        <style>
            :root {{
                --bg: #121217;
                --card-bg: #1e1e24;
                --green: #33d17a;
            }}
            body {{
                background: var(--bg);
                color: #fff;
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 2rem;
            }}
            .eyebrow {{
                color: var(--green);
            }}
            .order-id {{
                font-family: var(--font-mono);
                font-size: 1.5rem;
                color: #aaa;
                margin-bottom: 1.5rem;
            }}
            .card {{
                background: var(--card-bg);
                border: 1px solid #333;
                padding: 2rem;
                border-radius: 0;
            }}
            .status-icon {{
                font-size: 3rem;
                margin-bottom: 0.5rem;
            }}
            h2 {{
                color: #fff;
            }}
            .note, .tracking, .caption {{
                color: #888;
            }}
            .tracking code {{
                background: #2a2a30;
                padding: 0.25rem 0.5rem;
                border-radius: 4px;
                color: #ccc;
            }}
            footer {{
                margin-top: 2rem;
                color: #666;
            }}
        </style>
    </head>
    <body>
        <main class="container narrow" style="text-align: center;">
            <p class="eyebrow">Order Status</p>
            <div class="order-id">{escaped_order_id}</div>
            {status_html}
            <p class="caption" style="margin-top: 1.5rem;">You can come back to this page at any time to view your pending orders. You can also visit this page via <a href="https://hack.club/odr!{escaped_order_id}" style="color: var(--green);">hack.club/odr!{escaped_order_id}</a></p>
            <footer class="caption">Hermes by Jenin · <a href="mailto:hermes@hackclub.com" style="color: inherit;">Support</a></footer>
        </main>
    </body>
    </html>
    """

    return HTMLResponse(content=html_content)


@app.get("/api/v1/order/{order_id}/status", response_model=OrderStatusResponse)
@limiter.limit("60/minute")
async def get_order_status_api(
    request: Request,
    order_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get order status via API (public endpoint)."""
    stmt = select(Order).where(Order.order_id == order_id)
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return OrderStatusResponse(
        order_id=order.order_id,
        status=order.status,
        tracking_code=order.tracking_code,
        fulfillment_note=order.fulfillment_note,
        created_at=order.created_at,
        fulfilled_at=order.fulfilled_at
    )


async def update_financial_canvas(db: AsyncSession):
    """Updates the Slack canvas with current financial summary."""
    stmt = select(Event).where(Event.balance_due_cents > 0)
    result = await db.execute(stmt)
    events = result.scalars().all()

    unpaid_events = []
    total_due_cents = 0
    total_letters = 0
    total_ca = 0
    total_us = 0
    total_int = 0

    for event in events:
        last_letter_stmt = select(func.max(Letter.created_at)).where(Letter.event_id == event.id)
        last_letter_result = await db.execute(last_letter_stmt)
        last_letter_at = last_letter_result.scalar()

        letters_stmt = select(Letter.country).where(Letter.event_id == event.id)
        letters_result = await db.execute(letters_stmt)
        countries = letters_result.scalars().all()

        ca_count = sum(1 for c in countries if get_stamp_region(c) == "CA")
        us_count = sum(1 for c in countries if get_stamp_region(c) == "US")
        int_count = sum(1 for c in countries if get_stamp_region(c) == "INT")

        unpaid_events.append({
            "name": event.name,
            "letter_count": event.letter_count,
            "balance_due_cents": event.balance_due_cents,
            "last_letter_at": last_letter_at,
            "stamps_ca": ca_count,
            "stamps_us": us_count,
            "stamps_int": int_count
        })
        total_due_cents += event.balance_due_cents
        total_letters += event.letter_count
        total_ca += ca_count
        total_us += us_count
        total_int += int_count

    await slack_bot.update_financial_canvas(
        unpaid_events=unpaid_events,
        total_due_cents=total_due_cents,
        total_letters=total_letters,
        total_stamps_ca=total_ca,
        total_stamps_us=total_us,
        total_stamps_int=total_int
    )


@app.post("/slack/interactions")
async def handle_slack_interactions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    body: bytes = Depends(verify_slack_signature)
):
    """Handle Slack interactive component callbacks."""
    import json
    from urllib.parse import parse_qs

    parsed = parse_qs(body.decode())
    payload = json.loads(parsed.get("payload", ["{}"])[0])

    user_id = payload.get("user", {}).get("id")
    if user_id != settings.slack_jenin_user_id:
        logger.warning(f"Unauthorized Slack interaction attempt from user {user_id}")
        return JSONResponse(
            content={
                "response_action": "errors",
                "errors": {"general": "Unauthorized - only Jenin can use this bot"}
            }
        )

    payload_type = payload.get("type", "")

    if payload_type == "view_submission":
        callback_id = payload.get("view", {}).get("callback_id", "")
        values = payload.get("view", {}).get("state", {}).get("values", {})

        if callback_id.startswith("fulfill_order_modal:"):
            order_id = callback_id.replace("fulfill_order_modal:", "")
            tracking_code = values.get("tracking_code_block", {}).get("tracking_code", {}).get("value")
            fulfillment_note = values.get("fulfillment_note_block", {}).get("fulfillment_note", {}).get("value")

            errors = {}
            if tracking_code and len(tracking_code) > 64:
                errors["tracking_code_block"] = "Tracking code must be 64 characters or less"
            if fulfillment_note and len(fulfillment_note) > 500:
                errors["fulfillment_note_block"] = "Note must be 500 characters or less"
            if errors:
                return JSONResponse(content={"response_action": "errors", "errors": errors})

            stmt = select(Order).where(Order.order_id == order_id)
            result = await db.execute(stmt)
            order = result.scalar_one_or_none()

            if order:
                order.status = OrderStatus.FULFILLED
                order.fulfilled_at = datetime.utcnow()
                order.tracking_code = tracking_code
                order.fulfillment_note = fulfillment_note

                event_stmt = select(Event).where(Event.id == order.event_id)
                event_result = await db.execute(event_stmt)
                event = event_result.scalar_one_or_none()

                if event and order.slack_message_ts and order.slack_channel_id:
                    await slack_bot.update_order_fulfilled(
                        channel_id=order.slack_channel_id,
                        message_ts=order.slack_message_ts,
                        event_name=event.name,
                        order_id=order.order_id,
                        order_text=order.order_text,
                        status_url=get_order_status_url(order.order_id),
                        tracking_code=order.tracking_code,
                        fulfillment_note=order.fulfillment_note,
                        fulfilled_at=order.fulfilled_at
                    )

                await db.commit()

            return JSONResponse(content={"response_action": "clear"})

        elif callback_id.startswith("update_tracking_modal:"):
            order_id = callback_id.replace("update_tracking_modal:", "")
            tracking_code = values.get("tracking_code_block", {}).get("tracking_code", {}).get("value")

            if not tracking_code or len(tracking_code) < 1:
                return JSONResponse(content={"response_action": "errors", "errors": {"tracking_code_block": "Tracking code is required"}})
            if len(tracking_code) > 64:
                return JSONResponse(content={"response_action": "errors", "errors": {"tracking_code_block": "Tracking code must be 64 characters or less"}})

            stmt = select(Order).where(Order.order_id == order_id)
            result = await db.execute(stmt)
            order = result.scalar_one_or_none()

            if order:
                order.tracking_code = tracking_code

                event_stmt = select(Event).where(Event.id == order.event_id)
                event_result = await db.execute(event_stmt)
                event = event_result.scalar_one_or_none()

                if event and order.slack_message_ts and order.slack_channel_id:
                    await slack_bot.update_order_fulfilled(
                        channel_id=order.slack_channel_id,
                        message_ts=order.slack_message_ts,
                        event_name=event.name,
                        order_id=order.order_id,
                        order_text=order.order_text,
                        status_url=get_order_status_url(order.order_id),
                        tracking_code=order.tracking_code,
                        fulfillment_note=order.fulfillment_note,
                        fulfilled_at=order.fulfilled_at
                    )

                await db.commit()

            return JSONResponse(content={"response_action": "clear"})

    if payload_type == "block_actions":
        actions = payload.get("actions", [])
        trigger_id = payload.get("trigger_id")

        for action in actions:
            action_id = action.get("action_id", "")

            if action_id.startswith("mark_mailed:"):
                letter_id = action_id.replace("mark_mailed:", "")

                stmt = select(Letter).where(Letter.letter_id == letter_id)
                result = await db.execute(stmt)
                letter = result.scalar_one_or_none()

                if letter:
                    try:
                        await theseus_client.mark_letter_mailed(letter.letter_id)
                    except TheseusAPIError as e:
                        logger.error(f"Failed to mark letter {letter.letter_id} as mailed in Theseus: {e}")

                    letter.status = LetterStatus.SHIPPED
                    letter.mailed_at = datetime.utcnow()

                    event_stmt = select(Event).where(Event.id == letter.event_id)
                    event_result = await db.execute(event_stmt)
                    event = event_result.scalar_one_or_none()

                    if event and letter.slack_message_ts and letter.slack_channel_id:
                        await slack_bot.update_letter_shipped(
                            channel_id=letter.slack_channel_id,
                            message_ts=letter.slack_message_ts,
                            event_name=event.name,
                            queue_name=event.theseus_queue,
                            recipient_name=f"{letter.first_name} {letter.last_name}",
                            country=letter.country,
                            rubber_stamps_raw=letter.rubber_stamps_raw,
                            cost_cents=letter.cost_cents,
                            letter_id=letter.letter_id,
                            mailed_at=letter.mailed_at
                        )

                    await db.commit()

            elif action_id.startswith("fulfill_order:"):
                order_id = action_id.replace("fulfill_order:", "")
                if trigger_id:
                    await slack_bot.open_fulfill_order_modal(trigger_id, order_id)

            elif action_id.startswith("update_tracking:"):
                order_id = action_id.replace("update_tracking:", "")
                stmt = select(Order).where(Order.order_id == order_id)
                result = await db.execute(stmt)
                order = result.scalar_one_or_none()

                if trigger_id and order:
                    await slack_bot.open_update_tracking_modal(
                        trigger_id,
                        order_id,
                        order.tracking_code
                    )

    return JSONResponse(content={"ok": True})


@app.get("/")
@limiter.limit("60/minute")
async def root(request: Request):
    """Redirect to documentation page."""
    return RedirectResponse(url="/docs-page")


@app.get("/health")
@limiter.limit("60/minute")
async def health_check(request: Request):
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/docs-page", response_class=HTMLResponse)
@limiter.limit("60/minute")
async def get_docs_page(request: Request):
    """Serve the custom documentation page."""
    try:
        with open("docs/static_docs.html") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Documentation not found")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def catch_all_404(path: str, request: Request):
    """Catch-all route for undefined paths - returns proper 404."""
    accept_header = request.headers.get("accept", "")

    if "text/html" in accept_header:
        return HTMLResponse(
            content=get_404_html("Page Not Found", "The page you're looking for doesn't exist."),
            status_code=404
        )

    return JSONResponse(
        content={"detail": "Not Found", "path": f"/{path}"},
        status_code=404
    )
