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
async def handle_jenin_mail_command(ack, body, respond):
    """Handle the /jenin-mail slash command."""
    await ack()
    user_id = body.get("user_id", "unknown")
    text = body.get("text", "").strip()
    
    await respond(f"Hello <@{user_id}>! You ran /jenin-mail with: `{text}`")
    logger.info(f"/jenin-mail command from {user_id}: {text}")


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
