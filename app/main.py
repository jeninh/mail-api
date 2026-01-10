import logging
import hmac
import hashlib
import secrets
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db, init_db
from app.config import get_settings
from app.models import Event, Letter, LetterStatus, MailType
from app.schemas import (
    LetterCreate, LetterResponse, ErrorResponse, MarkPaidResponse,
    FinancialSummaryResponse, UnpaidEvent, StatusCheckResponse,
    CostCalculatorRequest, CostCalculatorResponse
)
from app.cost_calculator import (
    calculate_cost, cents_to_usd, CostCalculationError, ParcelQuoteRequired
)
from app.rubber_stamp_formatter import format_rubber_stamps
from app.theseus_client import theseus_client, TheseusAPIError
from app.slack_bot import slack_bot
from app.security import hash_api_key, verify_api_key
from app.background_jobs import start_scheduler, stop_scheduler, check_all_pending_letters
from app.slack_socket_handler import start_socket_mode, stop_socket_mode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()

# Simple in-memory rate limiter for failed auth attempts
# Tracks: {ip: [(timestamp, count)]}
_failed_auth_attempts: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX_ATTEMPTS = 10  # max failed attempts per window


def _check_rate_limit(client_ip: str) -> None:
    """Check if IP has exceeded rate limit for failed auth attempts."""
    now = time.time()
    attempts = _failed_auth_attempts[client_ip]
    
    # Clean old attempts outside window
    _failed_auth_attempts[client_ip] = [t for t in attempts if now - t < _RATE_LIMIT_WINDOW]
    
    if len(_failed_auth_attempts[client_ip]) >= _RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many failed authentication attempts. Try again later."
        )


def _record_failed_auth(client_ip: str) -> None:
    """Record a failed authentication attempt."""
    _failed_auth_attempts[client_ip].append(time.time())


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_scheduler()
    await start_socket_mode()
    logger.info("Application started")
    yield
    await stop_socket_mode()
    stop_scheduler()
    logger.info("Application stopped")


app = FastAPI(
    title="Theseus Mail Wrapper API",
    description="A wrapper API for Hack Club's Theseus mail system",
    version="1.0.0",
    lifespan=lifespan
)


async def verify_event_api_key(
    request: Request,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db)
) -> Event:
    """Verifies the event API key and returns the event."""
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)
    
    if not authorization.startswith("Bearer "):
        _record_failed_auth(client_ip)
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    
    api_key = authorization.replace("Bearer ", "")
    api_key_hashed = hash_api_key(api_key)
    
    stmt = select(Event).where(Event.api_key_hash == api_key_hashed)
    result = await db.execute(stmt)
    event = result.scalar_one_or_none()
    
    if not event:
        _record_failed_auth(client_ip)
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    return event


async def verify_admin_api_key(request: Request, authorization: str = Header(...)) -> bool:
    """Verifies the admin API key."""
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)
    
    if not authorization.startswith("Bearer "):
        _record_failed_auth(client_ip)
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    
    api_key = authorization.replace("Bearer ", "")
    
    if not secrets.compare_digest(api_key, settings.admin_api_key):
        _record_failed_auth(client_ip)
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
                detail="Weight exceeds 500g for bubble packets. A parcel is needed. Please DM @jenin on Slack or email jenin@hackclub.com for rates."
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
            detail="Mail service temporarily unavailable. Please DM @jenin on Slack."
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
    
    return LetterResponse(
        letter_id=letter_id,
        cost_usd=cents_to_usd(cost_cents),
        formatted_rubber_stamps=formatted_stamps,
        status=LetterStatus.QUEUED,
        theseus_url=theseus_client.get_public_letter_url(letter_id)
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
    
    for event in events:
        last_letter_stmt = select(func.max(Letter.created_at)).where(Letter.event_id == event.id)
        last_letter_result = await db.execute(last_letter_stmt)
        last_letter_at = last_letter_result.scalar()
        
        unpaid_events.append(UnpaidEvent(
            event_id=event.id,
            event_name=event.name,
            balance_due_usd=cents_to_usd(event.balance_due_cents),
            letter_count=event.letter_count,
            last_letter_at=last_letter_at
        ))
        total_due_cents += event.balance_due_cents
    
    return FinancialSummaryResponse(
        unpaid_events=unpaid_events,
        total_due_usd=cents_to_usd(total_due_cents)
    )


@app.post("/admin/check-letter-status", response_model=StatusCheckResponse)
async def manual_status_check(_: bool = Depends(verify_admin_api_key)):
    """Manually trigger a status check for all pending letters."""
    result = await check_all_pending_letters()
    return StatusCheckResponse(**result)


@app.post("/api/v1/calculate-cost", response_model=CostCalculatorResponse)
async def calculate_shipping_cost(request: CostCalculatorRequest):
    """Calculate shipping cost for a given mail type and destination."""
    try:
        cost_cents = calculate_cost(
            mail_type=request.mail_type,
            country=request.country,
            weight_grams=request.weight_grams
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


async def update_financial_canvas(db: AsyncSession):
    """Updates the Slack canvas with current financial summary."""
    stmt = select(Event).where(Event.balance_due_cents > 0)
    result = await db.execute(stmt)
    events = result.scalars().all()
    
    unpaid_events = []
    total_due_cents = 0
    total_letters = 0
    
    for event in events:
        last_letter_stmt = select(func.max(Letter.created_at)).where(Letter.event_id == event.id)
        last_letter_result = await db.execute(last_letter_stmt)
        last_letter_at = last_letter_result.scalar()
        
        unpaid_events.append({
            "name": event.name,
            "letter_count": event.letter_count,
            "balance_due_cents": event.balance_due_cents,
            "last_letter_at": last_letter_at
        })
        total_due_cents += event.balance_due_cents
        total_letters += event.letter_count
    
    await slack_bot.update_financial_canvas(
        unpaid_events=unpaid_events,
        total_due_cents=total_due_cents,
        total_letters=total_letters
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
    
    actions = payload.get("actions", [])
    
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
    
    return JSONResponse(content={"ok": True})


@app.get("/")
async def root():
    """Redirect to documentation page."""
    return RedirectResponse(url="/docs-page")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/docs-page", response_class=HTMLResponse)
async def get_docs_page():
    """Serve the custom documentation page."""
    try:
        with open("docs/static_docs.html", "r") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Documentation not found")
