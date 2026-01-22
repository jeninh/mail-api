import os

# Set test environment variables BEFORE any app imports
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("THESEUS_API_KEY", "test-theseus-key")
os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test-token")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test-token")
os.environ.setdefault("SLACK_SIGNING_SECRET", "test-signing-secret")
os.environ.setdefault("SLACK_NOTIFICATION_CHANNEL", "C12345678")
os.environ.setdefault("SLACK_CANVAS_ID", "F12345678")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
