import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Event, Letter, LetterStatus
from app.slack_bot import slack_bot
from app.theseus_client import TheseusAPIError, theseus_client

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def check_all_pending_letters() -> dict:
    """
    Checks status of all pending letters and updates accordingly.

    Runs every hour:
    1. Query all letters where status != 'shipped'
    2. For each, call Theseus API to get current status
    3. If status changed, update DB and Slack message
    4. If now 'shipped', mark as mailed and remove button

    Returns:
        Dict with checked, updated, and mailed counts
    """
    logger.info("Starting hourly letter status check")

    checked = 0
    updated = 0
    mailed = 0

    async with AsyncSessionLocal() as session:
        stmt = select(Letter).where(
            Letter.status.notin_([LetterStatus.SHIPPED, LetterStatus.FAILED])
        )
        result = await session.execute(stmt)
        letters = result.scalars().all()

        logger.info(f"Found {len(letters)} pending letters to check")

        for letter in letters:
            checked += 1

            try:
                theseus_response = await theseus_client.get_letter_status(letter.letter_id)
                new_status_str = theseus_response.get("status", "").lower()

                try:
                    new_status = LetterStatus(new_status_str)
                except ValueError:
                    logger.warning(f"Unknown status '{new_status_str}' for letter {letter.letter_id}")
                    continue

                if new_status != letter.status:
                    old_status = letter.status
                    letter.status = new_status
                    updated += 1

                    logger.info(f"Letter {letter.letter_id} status changed: {old_status} -> {new_status}")

                    if new_status == LetterStatus.SHIPPED:
                        letter.mailed_at = datetime.utcnow()
                        mailed += 1

                        if letter.slack_message_ts and letter.slack_channel_id:
                            event_stmt = select(Event).where(Event.id == letter.event_id)
                            event_result = await session.execute(event_stmt)
                            event = event_result.scalar_one_or_none()

                            if event:
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

                    await session.commit()

            except TheseusAPIError as e:
                logger.error(f"Failed to check status for letter {letter.letter_id}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error checking letter {letter.letter_id}: {e}")

    logger.info(f"Status check complete: checked={checked}, updated={updated}, mailed={mailed}")
    return {"checked": checked, "updated": updated, "mailed": mailed}


def start_scheduler():
    """Starts the background scheduler."""
    scheduler.add_job(
        check_all_pending_letters,
        'interval',
        hours=1,
        id='check_letter_status',
        replace_existing=True
    )
    scheduler.start()
    logger.info("Background scheduler started - checking letter status every hour")


def stop_scheduler():
    """Stops the background scheduler."""
    scheduler.shutdown()
    logger.info("Background scheduler stopped")
