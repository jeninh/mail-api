#!/usr/bin/env python3
"""
CLI script to create an API key for an event.

Usage:
    python scripts/create_api_key.py --event-name "Haxmas 2024" --queue-name "haxmas-2024-letters"

Or with explicit database URL:
    python scripts/create_api_key.py --database-url "postgresql://..." --event-name "Haxmas 2024" --queue-name "haxmas-2024-letters"
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Event
from app.security import generate_api_key, hash_api_key


async def create_event(database_url: str, event_name: str, queue_name: str) -> tuple[int, str]:
    """Create an event with a new API key."""
    engine = create_async_engine(database_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    api_key = generate_api_key()
    api_key_hash = hash_api_key(api_key)

    async with async_session() as session:
        event = Event(
            name=event_name,
            api_key_hash=api_key_hash,
            theseus_queue=queue_name,
            balance_due_cents=0,
            letter_count=0,
            is_paid=False
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        return event.id, api_key


def main():
    parser = argparse.ArgumentParser(description="Create an API key for an event")
    parser.add_argument(
        "--database-url",
        help="PostgreSQL database URL (or set DATABASE_URL env var)",
        default=os.environ.get("DATABASE_URL")
    )
    parser.add_argument(
        "--event-name",
        required=True,
        help="Name of the event (e.g., 'Haxmas 2024')"
    )
    parser.add_argument(
        "--queue-name",
        required=True,
        help="Theseus queue name (e.g., 'haxmas-2024-letters')"
    )

    args = parser.parse_args()

    if not args.database_url:
        print("Error: Database URL is required. Set DATABASE_URL env var or use --database-url")
        sys.exit(1)

    database_url = args.database_url
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    try:
        event_id, api_key = asyncio.run(
            create_event(database_url, args.event_name, args.queue_name)
        )

        print("\n✅ API Key Created")
        print(f"Event ID: {event_id}")
        print(f"Event: {args.event_name}")
        print(f"Queue: {args.queue_name}")
        print(f"API Key: {api_key}")
        print("\n⚠️  Keep this key secure! It cannot be retrieved again.")

    except Exception as e:
        print(f"\n❌ Error creating API key: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
