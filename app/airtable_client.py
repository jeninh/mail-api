import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

AIRTABLE_BASE_ID = "apppRJP4vjAfs2zKL"
AIRTABLE_TABLE_ID = "tbl6kTxCYvIPauSHr"

FIELD_IDS = {
    "first_name": "fldgrRCzkgpSFXUyS",
    "last_name": "fld0u431L2NRApSmu",
    "email": "fldaQFGktGtnz4n8F",
    "email_reason": "fldEFMt1Z42ERDxsa",
    "id": "fldaMPmwmz3daRYSb",
    "ysws": "fldxx3JWkIw4cQaOC",
    "contains": "fld8MD0dYkxOPedlO",
    "full_address": "fldpP8Xv02q9F472o",
}


class AirtableClient:
    def __init__(self):
        self.base_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_ID}"
        self.api_key = getattr(settings, 'airtable_api_key', None)

    async def create_record(
        self,
        first_name: str,
        last_name: str,
        email: str,
        email_reason: str,  # "Letter" or "Order"
        record_id: str,  # ltr! or odr! id
        ysws: str,  # Event name
        contains: str,  # What it contains (use <br> instead of \n)
        full_address: str,  # Formatted full address
    ) -> dict | None:
        if not self.api_key:
            logger.warning("Airtable API key not configured, skipping record creation")
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        contains_formatted = contains.replace("\n", "<br>") if contains else ""

        payload = {
            "fields": {
                FIELD_IDS["first_name"]: first_name,
                FIELD_IDS["last_name"]: last_name,
                FIELD_IDS["email"]: email,
                FIELD_IDS["email_reason"]: email_reason,
                FIELD_IDS["id"]: record_id,
                FIELD_IDS["ysws"]: ysws,
                FIELD_IDS["contains"]: contains_formatted,
                FIELD_IDS["full_address"]: full_address,
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=30.0,
                )
                response.raise_for_status()
                logger.info(f"Created Airtable record for {email_reason} {record_id}")
                result: dict[str, Any] = response.json()
                return result
        except httpx.HTTPStatusError as e:
            logger.error(f"Airtable API error: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Failed to create Airtable record: {e}")
            return None


airtable_client = AirtableClient()
