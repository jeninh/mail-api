from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

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

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    api_key_hash = Column(String(64), unique=True, nullable=False, index=True)
    theseus_queue = Column(String(255), nullable=False)
    balance_due_cents = Column(Integer, default=0, nullable=False)
    letter_count = Column(Integer, default=0, nullable=False)
    is_paid = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    letters = relationship("Letter", back_populates="event", lazy="dynamic")

    def __repr__(self):
        return f"<Event(id={self.id}, name='{self.name}')>"


class Letter(Base):
    __tablename__ = "letters"

    id = Column(Integer, primary_key=True, index=True)
    letter_id = Column(String(255), nullable=False, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    slack_message_ts = Column(String(255), nullable=True)
    slack_channel_id = Column(String(255), nullable=True)

    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    address_line_1 = Column(String(255), nullable=False)
    address_line_2 = Column(String(255), nullable=True)
    city = Column(String(255), nullable=False)
    state = Column(String(255), nullable=False)
    postal_code = Column(String(255), nullable=False)
    country = Column(String(255), nullable=False)
    recipient_email = Column(String(255), nullable=True)

    mail_type: "MailType" = Column(Enum(MailType), nullable=False)  # type: ignore[assignment]
    weight_grams = Column(Integer, nullable=True)
    rubber_stamps_raw = Column(Text, nullable=False)
    rubber_stamps_formatted = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)

    cost_cents = Column(Integer, nullable=False)
    status: "LetterStatus" = Column(Enum(LetterStatus), default=LetterStatus.QUEUED, nullable=False)  # type: ignore[assignment]
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    mailed_at = Column(DateTime, nullable=True)

    event = relationship("Event", back_populates="letters")

    __table_args__ = (
        Index("ix_letters_status", "status"),
        Index("ix_letters_event_id", "event_id"),
    )

    def __repr__(self):
        return f"<Letter(id={self.id}, letter_id='{self.letter_id}')>"


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String(7), unique=True, nullable=False, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)

    order_text = Column(Text, nullable=False)

    # NOTE: PII (name, address) is sent ONLY to Slack and NEVER stored in database

    status: "OrderStatus" = Column(Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False)  # type: ignore[assignment]
    tracking_code = Column(String(255), nullable=True)
    fulfillment_note = Column(Text, nullable=True)

    slack_message_ts = Column(String(255), nullable=True)
    slack_channel_id = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    fulfilled_at = Column(DateTime, nullable=True)

    event = relationship("Event", backref="orders")

    __table_args__ = (
        Index("ix_orders_status", "status"),
        Index("ix_orders_event_id", "event_id"),
    )

    def __repr__(self):
        return f"<Order(id={self.id}, order_id='{self.order_id}')>"
