import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class TheseusAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class TheseusClient:
    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.theseus_base_url.rstrip("/")
        self.api_key = self.settings.theseus_api_key

    def _get_headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    async def create_letter(
        self,
        queue_name: str,
        address: dict,
        rubber_stamps: str,
        recipient_email: str | None = None,
        notes: str | None = None
    ) -> dict:
        """
        Creates a letter in Theseus.

        Args:
            queue_name: The Theseus queue name
            address: Dict with first_name, last_name, line_1, line_2, city, state, postal_code, country
            rubber_stamps: Formatted rubber stamps text
            recipient_email: Optional email for tracking
            notes: Optional metadata notes

        Returns:
            Dict with id, status, tags, rubber_stamps, metadata

        Raises:
            TheseusAPIError: If API call fails
        """
        url = f"{self.base_url}/letter_queues/{queue_name}"

        payload: dict[str, Any] = {
            "address": {
                "first_name": address["first_name"],
                "last_name": address["last_name"],
                "line_1": address["line_1"],
                "line_2": address.get("line_2"),
                "city": address["city"],
                "state": address["state"],
                "postal_code": address["postal_code"],
                "country": address["country"]
            },
            "rubber_stamps": rubber_stamps,
            "metadata": {}
        }

        if notes:
            payload["metadata"]["notes"] = notes  # type: ignore[index]

        if recipient_email:
            payload["recipient_email"] = recipient_email

        logger.info(f"Creating letter in queue {queue_name} for {address['first_name']}, {address['country']} - stamps: {rubber_stamps}")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    json=payload,
                    timeout=30.0
                )

                if response.status_code not in (200, 201):
                    logger.error(f"Theseus API error creating letter: status {response.status_code}")
                    raise TheseusAPIError(
                        f"Theseus API error: status {response.status_code}",
                        status_code=response.status_code
                    )

                result: dict[str, Any] = response.json()
                logger.info(f"Letter created successfully: {result.get('id')}")
                return result

            except httpx.TimeoutException:
                logger.error("Theseus API timeout")
                raise TheseusAPIError("Theseus API timeout - please try again")
            except httpx.RequestError as e:
                logger.error(f"Theseus API request error: {e}")
                raise TheseusAPIError(f"Failed to connect to Theseus API: {str(e)}")

    async def get_letter_status(self, letter_id: str) -> dict:
        """
        Gets the current status of a letter from Theseus.

        Args:
            letter_id: The Theseus letter ID (e.g., "ltr!32jhyrnk")

        Returns:
            Dict with letter details including status

        Raises:
            TheseusAPIError: If API call fails
        """
        url = f"{self.base_url}/letters/{letter_id}"

        logger.info(f"Getting status for letter {letter_id}")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    url,
                    headers=self._get_headers(),
                    timeout=30.0
                )

                if response.status_code == 404:
                    raise TheseusAPIError(f"Letter not found: {letter_id}", status_code=404)

                if response.status_code != 200:
                    logger.error(f"Theseus API error getting letter status: status {response.status_code}")
                    raise TheseusAPIError(
                        f"Theseus API error: status {response.status_code}",
                        status_code=response.status_code
                    )

                result: dict[str, Any] = response.json()
                return result

            except httpx.TimeoutException:
                logger.error("Theseus API timeout")
                raise TheseusAPIError("Theseus API timeout - please try again")
            except httpx.RequestError as e:
                logger.error(f"Theseus API request error: {e}")
                raise TheseusAPIError(f"Failed to connect to Theseus API: {str(e)}")

    async def mark_letter_mailed(self, letter_id: str) -> dict[str, Any]:
        """
        Marks a letter as mailed in Theseus.

        Args:
            letter_id: The Theseus letter ID (e.g., "ltr!32jhyrnk")

        Returns:
            Dict with message confirming the letter was marked as mailed

        Raises:
            TheseusAPIError: If API call fails
        """
        url = f"{self.base_url}/letters/{letter_id}/mark_mailed"

        logger.info(f"Marking letter {letter_id} as mailed")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    timeout=30.0
                )

                if response.status_code == 404:
                    raise TheseusAPIError(f"Letter not found: {letter_id}", status_code=404)

                if response.status_code != 200:
                    logger.error(f"Theseus API error marking letter mailed: status {response.status_code}")
                    raise TheseusAPIError(
                        f"Theseus API error: status {response.status_code}",
                        status_code=response.status_code
                    )

                logger.info(f"Letter {letter_id} marked as mailed in Theseus")
                result: dict[str, Any] = response.json()
                return result

            except httpx.TimeoutException:
                logger.error("Theseus API timeout")
                raise TheseusAPIError("Theseus API timeout - please try again")
            except httpx.RequestError as e:
                logger.error(f"Theseus API request error: {e}")
                raise TheseusAPIError(f"Failed to connect to Theseus API: {str(e)}")

    def get_letter_url(self, letter_id: str) -> str:
        """Returns the back office URL for a letter (used in Slack)."""
        return f"https://mail.hackclub.com/back_office/letters/{letter_id}"

    def get_public_letter_url(self, letter_id: str) -> str:
        """Returns the public short URL for a letter (used in API responses)."""
        return f"https://hack.club/{letter_id}"

    def get_queue_url(self, queue_name: str) -> str:
        """Returns the back office URL for a queue."""
        return f"https://mail.hackclub.com/back_office/letter/queues/{queue_name}"


theseus_client = TheseusClient()


async def log_error(
    error_message: str,
    event_name: str = "Unknown",
    request_summary: str = "",
    notify_slack: bool = True
) -> None:
    """
    Logs an error to server logs and optionally sends a Slack notification.

    Args:
        error_message: The error message to log
        event_name: The event/context where the error occurred
        request_summary: Summary of the request that caused the error
        notify_slack: Whether to also send a Slack notification (default: True)
    """
    logger.error(f"[{event_name}] {error_message} | Request: {request_summary}")

    if notify_slack:
        try:
            from app.slack_bot import slack_bot
            await slack_bot.send_error_notification(
                event_name=event_name,
                error_message=error_message,
                request_summary=request_summary
            )
        except Exception as slack_error:
            logger.error(f"Failed to send Slack error notification: {slack_error}")
