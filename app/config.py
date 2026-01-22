from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str

    theseus_api_key: str
    theseus_base_url: str = "https://mail.hackclub.com/api/v1"

    slack_bot_token: str
    slack_app_token: str  # xapp-* token for Socket Mode
    slack_signing_secret: str  # For HTTP webhook verification
    slack_notification_channel: str
    slack_canvas_id: str
    slack_jenin_user_id: str = ""

    airtable_api_key: str = ""

    admin_api_key: str

    api_host: str = "0.0.0.0"  # nosec B104 - Intentional for container deployment
    api_port: int = 8000
    debug: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
