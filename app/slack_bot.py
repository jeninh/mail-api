import asyncio
import logging
from datetime import datetime
from functools import partial

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.config import get_settings
from app.cost_calculator import cents_to_usd
from app.rubber_stamp_formatter import format_for_slack_display

logger = logging.getLogger(__name__)


class SlackBot:
    def __init__(self):
        self.settings = get_settings()
        self.client = WebClient(token=self.settings.slack_bot_token)
        self.notification_channel = self.settings.slack_notification_channel
        self.canvas_id = self.settings.slack_canvas_id
        self.jenin_user_id = self.settings.slack_jenin_user_id

    async def _run_sync(self, func, *args, **kwargs):
        """Run a sync Slack SDK call in a thread pool to avoid blocking the event loop."""
        return await asyncio.to_thread(partial(func, *args, **kwargs))

    async def send_letter_created_notification(
        self,
        event_name: str,
        queue_name: str,
        recipient_name: str,
        country: str,
        rubber_stamps_raw: str,
        cost_cents: int,
        notes: str | None,
        letter_id: str
    ) -> tuple[str, str]:
        """
        Sends a notification when a letter is created.

        Returns:
            Tuple of (message_ts, channel_id) for later editing
        """
        items_display = format_for_slack_display(rubber_stamps_raw)
        cost_usd = cents_to_usd(cost_cents)

        letter_url = f"https://mail.hackclub.com/back_office/letters/{letter_id}"
        queue_url = f"https://mail.hackclub.com/back_office/letter/queues/{queue_name}"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "📬 New Letter Created",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Event:* {event_name} | *Queue:* {queue_name}\n*Recipient:* {recipient_name}, {country}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Items to Pack:*\n{items_display}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Cost:* ${cost_usd:.2f} USD"
                }
            }
        ]

        if notes:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Notes:* {notes}"
                }
            })

        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "View in Theseus"
                    },
                    "url": letter_url,
                    "action_id": "view_letter"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "View Queue"
                    },
                    "url": queue_url,
                    "action_id": "view_queue"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Mark as Mailed"
                    },
                    "style": "primary",
                    "action_id": f"mark_mailed:{letter_id}",
                    "value": letter_id
                }
            ]
        })

        try:
            response = await self._run_sync(
                self.client.chat_postMessage,
                channel=self.notification_channel,
                blocks=blocks,
                text=f"New letter created for {recipient_name}"
            )
            logger.info(f"Slack notification sent for letter {letter_id}")
            return response["ts"], response["channel"]
        except SlackApiError as e:
            logger.error(f"Failed to send Slack notification: {e}")
            raise

    async def update_letter_shipped(
        self,
        channel_id: str,
        message_ts: str,
        event_name: str,
        queue_name: str,
        recipient_name: str,
        country: str,
        rubber_stamps_raw: str,
        cost_cents: int,
        letter_id: str,
        mailed_at: datetime
    ) -> None:
        """Updates the Slack message when a letter is shipped."""
        items_display = format_for_slack_display(rubber_stamps_raw)
        cost_usd = cents_to_usd(cost_cents)
        mailed_str = mailed_at.strftime("%Y-%m-%d %I:%M %p")

        letter_url = f"https://mail.hackclub.com/back_office/letters/{letter_id}"
        queue_url = f"https://mail.hackclub.com/back_office/letter/queues/{queue_name}"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "✅ Letter Mailed",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Event:* {event_name} | *Queue:* {queue_name}\n*Recipient:* {recipient_name}, {country}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Items to Pack:*\n{items_display}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Cost:* ${cost_usd:.2f} USD\n*Mailed:* {mailed_str}"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "View in Theseus"
                        },
                        "url": letter_url,
                        "action_id": "view_letter"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "View Queue"
                        },
                        "url": queue_url,
                        "action_id": "view_queue"
                    }
                ]
            }
        ]

        try:
            await self._run_sync(
                self.client.chat_update,
                channel=channel_id,
                ts=message_ts,
                blocks=blocks,
                text=f"Letter mailed to {recipient_name}"
            )
            logger.info(f"Slack message updated for shipped letter {letter_id}")
        except SlackApiError as e:
            logger.error(f"Failed to update Slack message: {e}")

    async def send_error_notification(
        self,
        event_name: str,
        error_message: str,
        request_summary: str
    ) -> None:
        """Sends an error notification to the channel."""
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🚨 Error Creating Letter",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Event:* {event_name}\n*Error:* {error_message}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Request:* {request_summary}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<@{self.jenin_user_id}> - Please investigate" if self.jenin_user_id else "@jenin - Please investigate"
                }
            }
        ]

        try:
            await self._run_sync(
                self.client.chat_postMessage,
                channel=self.notification_channel,
                blocks=blocks,
                text=f"Error creating letter for {event_name}"
            )
            logger.info(f"Error notification sent for {event_name}")
        except SlackApiError as e:
            logger.error(f"Failed to send error notification: {e}")

    async def send_parcel_quote_request(
        self,
        event_name: str,
        weight_grams: int,
        country: str,
        recipient_name: str,
        rubber_stamps_raw: str,
        letter_id: str
    ) -> None:
        """Sends a DM to Jenin requesting a parcel quote."""
        if not self.jenin_user_id:
            logger.warning("SLACK_JENIN_USER_ID not set, cannot send parcel DM")
            return

        items_display = format_for_slack_display(rubber_stamps_raw)
        letter_url = f"https://mail.hackclub.com/back_office/letters/{letter_id}"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "📦 Parcel Quote Requested",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Event:* {event_name}\n*Weight:* {weight_grams}g\n*Destination:* {country}\n*Recipient:* {recipient_name}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Items to Pack:*\n{items_display}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Please provide a quote for this parcel."
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "View Letter"
                        },
                        "url": letter_url,
                        "action_id": "view_letter"
                    }
                ]
            }
        ]

        try:
            await self._run_sync(
                self.client.chat_postMessage,
                channel=self.jenin_user_id,
                blocks=blocks,
                text=f"Parcel quote requested for {event_name}"
            )
            logger.info(f"Parcel quote DM sent for {event_name}")
        except SlackApiError as e:
            logger.error(f"Failed to send parcel quote DM: {e}")

    async def send_server_lifecycle_notification(
        self,
        event_type: str,
        details: str | None = None
    ) -> None:
        """
        Sends server lifecycle notifications to Slack.

        Args:
            event_type: Type of event (e.g., 'startup', 'shutdown', 'scheduler_started', etc.)
            details: Optional additional details about the event
        """
        event_config = {
            "startup": {"emoji": "🚀", "title": "Server Started", "color": "#36a64f"},
            "shutdown": {"emoji": "🛑", "title": "Server Stopped", "color": "#ff6b6b"},
            "scheduler_started": {"emoji": "⏰", "title": "Background Scheduler Started", "color": "#4ecdc4"},
            "scheduler_stopped": {"emoji": "⏹️", "title": "Background Scheduler Stopped", "color": "#ffe66d"},
            "socket_mode_connected": {"emoji": "🔌", "title": "Slack Socket Mode Connected", "color": "#4ecdc4"},
            "socket_mode_disconnected": {"emoji": "🔌", "title": "Slack Socket Mode Disconnected", "color": "#ffe66d"},
            "database_connected": {"emoji": "🗄️", "title": "Database Connected", "color": "#4ecdc4"},
            "error": {"emoji": "💥", "title": "Server Error", "color": "#ff6b6b"},
        }

        config = event_config.get(event_type, {"emoji": "ℹ️", "title": event_type.replace("_", " ").title(), "color": "#cccccc"})
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{config['emoji']} {config['title']}",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Timestamp:* {timestamp}"
                }
            }
        ]

        if details:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Details:* {details}"
                }
            })

        try:
            await self._run_sync(
                self.client.chat_postMessage,
                channel=self.notification_channel,
                blocks=blocks,
                text=f"{config['title']}: {details or 'No additional details'}"
            )
            logger.info(f"Server lifecycle notification sent: {event_type}")
        except SlackApiError as e:
            logger.error(f"Failed to send lifecycle notification: {e}")

    async def update_financial_canvas(
        self,
        unpaid_events: list[dict],
        total_due_cents: int,
        total_letters: int,
        total_stamps_ca: int = 0,
        total_stamps_us: int = 0,
        total_stamps_int: int = 0
    ) -> None:
        """Updates the Slack Canvas with financial summary."""
        now = datetime.utcnow().strftime("%b %d, %Y %I:%M %p")
        total_due_usd = cents_to_usd(total_due_cents)

        content = "# 💰 Theseus Mail Financial Summary\n\n"
        content += f"**Last Updated:** {now}\n\n"
        content += "## Unpaid Events\n\n"

        if not unpaid_events:
            content += "_No unpaid events_\n\n"
        else:
            for event in unpaid_events:
                balance_usd = cents_to_usd(event["balance_due_cents"])
                last_letter = event.get("last_letter_at", "N/A")
                if isinstance(last_letter, datetime):
                    last_letter = last_letter.strftime("%Y-%m-%d %I:%M %p")

                stamps_ca = event.get("stamps_ca", 0)
                stamps_us = event.get("stamps_us", 0)
                stamps_int = event.get("stamps_int", 0)

                content += f"**{event['name']}**\n"
                content += f"- Letters: {event['letter_count']}\n"
                content += f"- Stamps: 🇨🇦 {stamps_ca} | 🇺🇸 {stamps_us} | 🌍 {stamps_int}\n"
                content += f"- Balance Due: ${balance_usd:.2f} USD\n"
                content += f"- Last Letter: {last_letter}\n\n"

        content += "---\n\n"
        content += f"**Total Due:** ${total_due_usd:.2f} USD\n"
        content += f"**Total Letters:** {total_letters}\n"
        content += f"**Total Stamps:** 🇨🇦 {total_stamps_ca} | 🇺🇸 {total_stamps_us} | 🌍 {total_stamps_int}\n"

        try:
            await self._run_sync(
                self.client.canvases_edit,
                canvas_id=self.canvas_id,
                changes=[
                    {
                        "operation": "replace",
                        "document_content": {
                            "type": "markdown",
                            "markdown": content
                        }
                    }
                ]
            )
            logger.info("Financial canvas updated")
        except SlackApiError as e:
            logger.error(f"Failed to update financial canvas: {e}")


    async def send_order_notification(
        self,
        event_name: str,
        order_id: str,
        order_text: str,
        status_url: str,
        first_name: str,
        last_name: str,
        email: str | None,
        phone_number: str | None,
        address_line_1: str,
        address_line_2: str | None,
        city: str,
        state: str,
        postal_code: str,
        country: str,
        order_notes: str | None
    ) -> tuple[str, str]:
        """
        Sends a notification when an order is created.

        PII is included in this message and NEVER stored in the database.
        This is the only place the shipping address exists.

        Returns:
            Tuple of (message_ts, channel_id) for later editing
        """
        address_parts = [address_line_1]
        if address_line_2:
            address_parts.append(address_line_2)
        address_parts.append(f"{city}, {state} {postal_code}")
        address_parts.append(country)
        address_text = "\n".join(address_parts)

        email_text = f"\n*Email:* {email}" if email else ""
        phone_text = f"\n*Phone:* {phone_number}" if phone_number else ""

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "📦 New Order Request",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Event:* {event_name}\n*Order ID:* `{order_id}`"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Order Details:*\n{order_text}"
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Ship To:*\n*{first_name} {last_name}*\n{address_text}{email_text}{phone_text}"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "⚠️ Address is shown here ONLY and NOT stored in database"
                    }
                ]
            },
        ]

        if order_notes:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Notes:*\n{order_notes}"
                }
            })

        blocks.extend([
            {
                "type": "divider"
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "💵 $1 fee per item • Charged to event's HCB"
                    }
                ]
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "View Status Page"
                        },
                        "url": status_url,
                        "action_id": "view_order_status"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Mark Fulfilled"
                        },
                        "style": "primary",
                        "action_id": f"fulfill_order:{order_id}",
                        "value": order_id
                    }
                ]
            }
        ])

        try:
            response = await self._run_sync(
                self.client.chat_postMessage,
                channel=self.notification_channel,
                blocks=blocks,
                text=f"New order request from {event_name}"
            )
            logger.info(f"Slack notification sent for order {order_id}")
            return response["ts"], response["channel"]
        except SlackApiError as e:
            logger.error(f"Failed to send Slack notification: {e}")
            raise

    async def update_order_fulfilled(
        self,
        channel_id: str,
        message_ts: str,
        event_name: str,
        order_id: str,
        order_text: str,
        status_url: str,
        tracking_code: str | None,
        fulfillment_note: str | None,
        fulfilled_at: datetime
    ) -> None:
        """Updates the Slack message when an order is fulfilled."""
        fulfilled_str = fulfilled_at.strftime("%Y-%m-%d %I:%M %p")

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "✅ Order Fulfilled",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Event:* {event_name}\n*Order ID:* `{order_id}`"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Order Details:*\n{order_text}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Fulfilled:* {fulfilled_str}"
                }
            }
        ]

        if tracking_code:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Tracking Code:* `{tracking_code}`"
                }
            })

        if fulfillment_note:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Note:* {fulfillment_note}"
                }
            })

        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "View Status Page"
                    },
                    "url": status_url,
                    "action_id": "view_order_status"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Update Tracking"
                    },
                    "action_id": f"update_tracking:{order_id}",
                    "value": order_id
                }
            ]
        })

        try:
            await self._run_sync(
                self.client.chat_update,
                channel=channel_id,
                ts=message_ts,
                blocks=blocks,
                text=f"Order {order_id} fulfilled"
            )
            logger.info(f"Slack message updated for fulfilled order {order_id}")
        except SlackApiError as e:
            logger.error(f"Failed to update Slack message: {e}")

    async def open_fulfill_order_modal(
        self,
        trigger_id: str,
        order_id: str
    ) -> None:
        """Opens a modal to fulfill an order with optional tracking code and note."""
        view = {
            "type": "modal",
            "callback_id": f"fulfill_order_modal:{order_id}",
            "title": {
                "type": "plain_text",
                "text": "Fulfill Order"
            },
            "submit": {
                "type": "plain_text",
                "text": "Fulfill"
            },
            "close": {
                "type": "plain_text",
                "text": "Cancel"
            },
            "blocks": [
                {
                    "type": "input",
                    "block_id": "tracking_code_block",
                    "optional": True,
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "tracking_code",
                        "max_length": 64,
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Enter tracking code (optional)"
                        }
                    },
                    "label": {
                        "type": "plain_text",
                        "text": "Tracking Code"
                    }
                },
                {
                    "type": "input",
                    "block_id": "fulfillment_note_block",
                    "optional": True,
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "fulfillment_note",
                        "multiline": True,
                        "max_length": 500,
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Enter any notes (optional)"
                        }
                    },
                    "label": {
                        "type": "plain_text",
                        "text": "Note"
                    }
                }
            ]
        }

        try:
            await self._run_sync(
                self.client.views_open,
                trigger_id=trigger_id,
                view=view
            )
            logger.info(f"Opened fulfill modal for order {order_id}")
        except SlackApiError as e:
            logger.error(f"Failed to open fulfill modal: {e}")

    async def open_update_tracking_modal(
        self,
        trigger_id: str,
        order_id: str,
        current_tracking: str | None = None
    ) -> None:
        """Opens a modal to update tracking code for an order."""
        view = {
            "type": "modal",
            "callback_id": f"update_tracking_modal:{order_id}",
            "title": {
                "type": "plain_text",
                "text": "Update Tracking"
            },
            "submit": {
                "type": "plain_text",
                "text": "Update"
            },
            "close": {
                "type": "plain_text",
                "text": "Cancel"
            },
            "blocks": [
                {
                    "type": "input",
                    "block_id": "tracking_code_block",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "tracking_code",
                        "initial_value": current_tracking or "",
                        "min_length": 1,
                        "max_length": 64,
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Enter new tracking code"
                        }
                    },
                    "label": {
                        "type": "plain_text",
                        "text": "Tracking Code"
                    }
                }
            ]
        }

        try:
            await self._run_sync(
                self.client.views_open,
                trigger_id=trigger_id,
                view=view
            )
            logger.info(f"Opened update tracking modal for order {order_id}")
        except SlackApiError as e:
            logger.error(f"Failed to open update tracking modal: {e}")


slack_bot = SlackBot()
