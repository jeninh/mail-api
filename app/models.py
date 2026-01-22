from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MailType(str, PyEnum):
    LETTERMAIL = "lettermail"
    BUBBLE_PACKET = "bubble_packet"
    PARCEL = "parcel"


class LetterStatus(str, PyEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    FAILED = "failed"


class OrderStatus(str, PyEnum):
    PENDING = "pending"
    FULFILLED = "fulfilled"


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    theseus_queue: Mapped[str] = mapped_column(String(255), nullable=False)
    balance_due_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    letter_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    letters: Mapped[list["Letter"]] = relationship("Letter", back_populates="event", lazy="dynamic")

    def __repr__(self):
        return f"<Event(id={self.id}, name='{self.name}')>"


class Letter(Base):
    __tablename__ = "letters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    letter_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("events.id"), nullable=False)
    slack_message_ts: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    slack_channel_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line_1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line_2: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(255), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    mail_type: Mapped[MailType] = mapped_column(Enum(MailType), nullable=False)
    weight_grams: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rubber_stamps_raw: Mapped[str] = mapped_column(Text, nullable=False)
    rubber_stamps_formatted: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    cost_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[LetterStatus] = mapped_column(
        Enum(LetterStatus), default=LetterStatus.QUEUED, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    mailed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    event: Mapped[Event] = relationship("Event", back_populates="letters")

    __table_args__ = (
        Index("ix_letters_status", "status"),
        Index("ix_letters_event_id", "event_id"),
    )

    def __repr__(self):
        return f"<Letter(id={self.id}, letter_id='{self.letter_id}')>"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_id: Mapped[str] = mapped_column(String(7), unique=True, nullable=False, index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("events.id"), nullable=False)

    order_text: Mapped[str] = mapped_column(Text, nullable=False)

    # NOTE: PII (name, address) is sent ONLY to Slack and NEVER stored in database

    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False
    )
    tracking_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    fulfillment_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    slack_message_ts: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    slack_channel_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    fulfilled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    event: Mapped[Event] = relationship("Event", backref="orders")

    __table_args__ = (
        Index("ix_orders_status", "status"),
        Index("ix_orders_event_id", "event_id"),
    )

    def __repr__(self):
        return f"<Order(id={self.id}, order_id='{self.order_id}')>"
