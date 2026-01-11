import asyncio
import logging
import re
from datetime import datetime
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Letter, Event, LetterStatus
from app.slack_bot import slack_bot
from app.theseus_client import theseus_client, TheseusAPIError

logger = logging.getLogger(__name__)
settings = get_settings()

bolt_app = AsyncApp(
    token=settings.slack_bot_token,
    signing_secret=settings.slack_signing_secret,
)


@bolt_app.action({"action_id": re.compile(r"^mark_mailed:")})
async def handle_mark_mailed(ack, body, action):
    """Handle the 'Mark as Mailed' button click via Socket Mode."""
    await ack()
    
    action_id = action.get("action_id", "")
    if not action_id.startswith("mark_mailed:"):
        return
    
    letter_id = action_id.replace("mark_mailed:", "")
    
    async with AsyncSessionLocal() as db:
        stmt = select(Letter).where(Letter.letter_id == letter_id)
        result = await db.execute(stmt)
        letter = result.scalar_one_or_none()
        
        if not letter:
            logger.warning(f"Letter {letter_id} not found for mark_mailed action")
            return
        
        if letter.status == LetterStatus.SHIPPED:
            logger.info(f"Letter {letter_id} already marked as shipped")
            return
        
        try:
            await theseus_client.mark_letter_mailed(letter.letter_id)
        except TheseusAPIError as e:
            logger.error(f"Failed to mark letter {letter_id} as mailed in Theseus: {e}")
        
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
        logger.info(f"Letter {letter_id} marked as mailed via Socket Mode")


@bolt_app.command("/jenin-mail")
async def handle_jenin_mail_command(ack, body, client, respond):
    """Handle the /jenin-mail slash command."""
    await ack()
    user_id = body.get("user_id", "unknown")
    trigger_id = body.get("trigger_id")
    text = body.get("text", "").strip().lower()
    
    logger.info(f"/jenin-mail command from {user_id}: {text}")
    
    if user_id != settings.slack_jenin_user_id:
        await respond(response_type="ephemeral", text="Unauthorized")
        return
    
    if text == "paid":
        await handle_paid_command(client, trigger_id, respond)
    elif text == "summary":
        await handle_summary_command(respond)
    elif text == "status":
        await handle_status_command(respond)
    else:
        await respond(
            response_type="ephemeral",
            text=(
                "❓ *Unknown Command*\n\n"
                "Available commands:\n"
                "• `/jenin-mail paid` - Mark an event as paid\n"
                "• `/jenin-mail summary` - View financial summary\n"
                "• `/jenin-mail status` - Check system status"
            )
        )


async def handle_paid_command(client, trigger_id, respond):
    """Open a modal to mark an event as paid."""
    from sqlalchemy import select
    from app.models import Event
    from app.cost_calculator import cents_to_usd
    
    async with AsyncSessionLocal() as db:
        stmt = select(Event).where(Event.balance_due_cents > 0)
        result = await db.execute(stmt)
        events = result.scalars().all()
    
    if not events:
        await respond(
            response_type="ephemeral",
            text="✅ No unpaid events found!"
        )
        return
    
    options = []
    for event in events:
        balance_usd = cents_to_usd(event.balance_due_cents)
        options.append({
            "text": {
                "type": "plain_text",
                "text": f"{event.name} - ${balance_usd:.2f}"
            },
            "value": str(event.id)
        })
    
    modal = {
        "type": "modal",
        "callback_id": "mark_event_paid",
        "title": {
            "type": "plain_text",
            "text": "Mark Event as Paid"
        },
        "submit": {
            "type": "plain_text",
            "text": "Confirm Payment"
        },
        "close": {
            "type": "plain_text",
            "text": "Cancel"
        },
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Select an event to mark as paid:"
                }
            },
            {
                "type": "input",
                "block_id": "event_select",
                "element": {
                    "type": "static_select",
                    "action_id": "event_selection",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Choose an event"
                    },
                    "options": options
                },
                "label": {
                    "type": "plain_text",
                    "text": "Event"
                }
            }
        ]
    }
    
    try:
        await client.views_open(
            trigger_id=trigger_id,
            view=modal
        )
    except Exception as e:
        logger.error(f"Failed to open paid modal: {e}")
        await respond(
            response_type="ephemeral",
            text="❌ Failed to open modal. Please try again."
        )


async def handle_summary_command(respond):
    """Show a financial summary of all unpaid events."""
    from sqlalchemy import select
    from app.models import Event, Letter
    from app.cost_calculator import cents_to_usd, get_stamp_region
    
    async with AsyncSessionLocal() as db:
        stmt = select(Event).where(Event.balance_due_cents > 0)
        result = await db.execute(stmt)
        events = result.scalars().all()
        
        if not events:
            await respond(
                response_type="ephemeral",
                text="✅ No unpaid events! All balances are settled."
            )
            return
        
        total_due_cents = 0
        total_letters = 0
        total_ca = 0
        total_us = 0
        total_int = 0
        lines = ["💰 *Financial Summary*\n", "*Unpaid Events:*"]
        
        for event in events:
            letters_stmt = select(Letter.country).where(Letter.event_id == event.id)
            letters_result = await db.execute(letters_stmt)
            countries = letters_result.scalars().all()
            
            ca_count = sum(1 for c in countries if get_stamp_region(c) == "CA")
            us_count = sum(1 for c in countries if get_stamp_region(c) == "US")
            int_count = sum(1 for c in countries if get_stamp_region(c) == "INT")
            
            balance_usd = cents_to_usd(event.balance_due_cents)
            lines.append(f"• {event.name}: {event.letter_count} letters → ${balance_usd:.2f}")
            lines.append(f"    🇨🇦 {ca_count} | 🇺🇸 {us_count} | 🌍 {int_count}")
            
            total_due_cents += event.balance_due_cents
            total_letters += event.letter_count
            total_ca += ca_count
            total_us += us_count
            total_int += int_count
    
    total_usd = cents_to_usd(total_due_cents)
    lines.append(f"\n*Total Due:* ${total_usd:.2f}")
    lines.append(f"*Total Letters:* {total_letters}")
    lines.append(f"*Total Stamps:* 🇨🇦 {total_ca} | 🇺🇸 {total_us} | 🌍 {total_int}")
    lines.append("\n_Use `/jenin-mail paid` to mark an event as paid._")
    
    await respond(
        response_type="ephemeral",
        text="\n".join(lines)
    )


async def handle_status_command(respond):
    """Show current system status and statistics."""
    from sqlalchemy import select, func
    from app.models import Letter, LetterStatus
    
    async with AsyncSessionLocal() as db:
        status_counts = {}
        for status in LetterStatus:
            stmt = select(func.count(Letter.id)).where(Letter.status == status)
            result = await db.execute(stmt)
            status_counts[status.value] = result.scalar() or 0
        
        last_letter_stmt = select(Letter).order_by(Letter.created_at.desc()).limit(1)
        last_letter_result = await db.execute(last_letter_stmt)
        last_letter = last_letter_result.scalar_one_or_none()
        
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_stmt = select(func.count(Letter.id)).where(Letter.created_at >= today_start)
        today_result = await db.execute(today_stmt)
        letters_today = today_result.scalar() or 0
    
    lines = [
        "📊 *System Status*\n",
        "*Letters by Status:*",
        f"• Queued: {status_counts.get('queued', 0)}",
        f"• Processing: {status_counts.get('processing', 0)}",
        f"• Shipped: {status_counts.get('shipped', 0)}",
        f"• Failed: {status_counts.get('failed', 0)}",
        "",
        "*Recent Activity:*",
    ]
    
    if last_letter:
        event_name = "Unknown"
        async with AsyncSessionLocal() as db:
            from app.models import Event
            event_stmt = select(Event).where(Event.id == last_letter.event_id)
            event_result = await db.execute(event_stmt)
            event = event_result.scalar_one_or_none()
            if event:
                event_name = event.name
        
        time_ago = datetime.utcnow() - last_letter.created_at
        minutes_ago = int(time_ago.total_seconds() / 60)
        if minutes_ago < 60:
            time_str = f"{minutes_ago} minute{'s' if minutes_ago != 1 else ''} ago"
        else:
            hours_ago = minutes_ago // 60
            time_str = f"{hours_ago} hour{'s' if hours_ago != 1 else ''} ago"
        
        lines.append(f"• Last letter created: {time_str} ({event_name})")
    else:
        lines.append("• No letters created yet")
    
    lines.append(f"• Letters created today: {letters_today}")
    
    await respond(
        response_type="ephemeral",
        text="\n".join(lines)
    )


@bolt_app.view("mark_event_paid")
async def handle_mark_event_paid_submission(ack, body, client):
    """Handle the modal submission to mark an event as paid."""
    await ack()
    
    user_id = body["user"]["id"]
    values = body["view"]["state"]["values"]
    event_id = int(values["event_select"]["event_selection"]["selected_option"]["value"])
    
    from sqlalchemy import select
    from app.models import Event
    from app.cost_calculator import cents_to_usd
    
    async with AsyncSessionLocal() as db:
        stmt = select(Event).where(Event.id == event_id)
        result = await db.execute(stmt)
        event = result.scalar_one_or_none()
        
        if not event:
            logger.error(f"Event {event_id} not found for mark_paid")
            return
        
        previous_balance = event.balance_due_cents
        event.balance_due_cents = 0
        event.is_paid = True
        await db.commit()
        
        event_name = event.name
    
    balance_usd = cents_to_usd(previous_balance)
    
    try:
        await client.chat_postMessage(
            channel=settings.slack_notification_channel,
            text=(
                f"✅ *Event Marked as Paid*\n\n"
                f"*Event:* {event_name}\n"
                f"*Amount:* ${balance_usd:.2f} USD\n"
                f"*Marked by:* <@{user_id}>"
            )
        )
    except Exception as e:
        logger.error(f"Failed to post payment confirmation: {e}")
    
    try:
        from app.slack_bot import slack_bot
        stmt = select(Event).where(Event.balance_due_cents > 0)
        async with AsyncSessionLocal() as db:
            result = await db.execute(stmt)
            events = result.scalars().all()
            
            unpaid_events = []
            total_due_cents = 0
            total_letters = 0
            
            for evt in events:
                unpaid_events.append({
                    "name": evt.name,
                    "letter_count": evt.letter_count,
                    "balance_due_cents": evt.balance_due_cents
                })
                total_due_cents += evt.balance_due_cents
                total_letters += evt.letter_count
            
            await slack_bot.update_financial_canvas(unpaid_events, total_due_cents, total_letters)
    except Exception as e:
        logger.error(f"Failed to update canvas after payment: {e}")
    
    logger.info(f"Event {event_name} marked as paid by {user_id}")


socket_mode_handler: AsyncSocketModeHandler = None


async def start_socket_mode():
    """Start the Socket Mode handler."""
    global socket_mode_handler
    socket_mode_handler = AsyncSocketModeHandler(bolt_app, settings.slack_app_token)
    await socket_mode_handler.connect_async()
    logger.info("Slack Socket Mode handler started")


async def stop_socket_mode():
    """Stop the Socket Mode handler."""
    global socket_mode_handler
    if socket_mode_handler:
        await socket_mode_handler.close_async()
        logger.info("Slack Socket Mode handler stopped")
