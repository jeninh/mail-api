from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models import LetterStatus, MailType, OrderStatus


class LetterCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=255)
    last_name: str = Field(..., min_length=1, max_length=255)
    address_line_1: str = Field(..., min_length=1, max_length=255)
    address_line_2: str | None = Field(None, max_length=255)
    city: str = Field(..., min_length=1, max_length=255)
    state: str = Field(..., min_length=1, max_length=255)
    postal_code: str = Field(..., min_length=1, max_length=255)
    country: str = Field(..., min_length=1, max_length=255)
    recipient_email: EmailStr | None = None
    mail_type: MailType
    weight_grams: int | None = Field(None, ge=1)
    rubber_stamps: str = Field(..., min_length=1)
    notes: str | None = None

    @field_validator("weight_grams")
    @classmethod
    def validate_weight(cls, v, info):
        mail_type = info.data.get("mail_type")
        if mail_type in [MailType.BUBBLE_PACKET, MailType.PARCEL] and v is None:
            raise ValueError("weight_grams is required for bubble_packet and parcel")
        return v


class LetterResponse(BaseModel):
    letter_id: str
    cost_usd: float
    formatted_rubber_stamps: str
    status: LetterStatus
    theseus_url: str
    email_sent: bool = False

    class Config:
        from_attributes = True


class ErrorResponse(BaseModel):
    error: str


class MarkPaidResponse(BaseModel):
    event_id: int
    event_name: str
    previous_balance_cents: int
    new_balance_cents: int
    is_paid: bool


class StampCounts(BaseModel):
    canada: int = 0
    us: int = 0
    international: int = 0


class UnpaidEvent(BaseModel):
    event_id: int
    event_name: str
    balance_due_usd: float
    letter_count: int
    stamps: StampCounts
    last_letter_at: datetime | None

    class Config:
        from_attributes = True


class FinancialSummaryResponse(BaseModel):
    unpaid_events: list[UnpaidEvent]
    total_due_usd: float
    total_stamps: StampCounts


class StatusCheckResponse(BaseModel):
    checked: int
    updated: int
    mailed: int


class CostCalculatorRequest(BaseModel):
    country: str
    mail_type: MailType
    weight_grams: int | None = None


class CostCalculatorResponse(BaseModel):
    cost_cents: int
    cost_usd: float
    message: str | None = None


class EventCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    queue_name: str = Field(..., min_length=1, max_length=255)


class EventResponse(BaseModel):
    id: int
    name: str
    theseus_queue: str
    balance_due_cents: int
    letter_count: int
    is_paid: bool
    created_at: datetime

    class Config:
        from_attributes = True


class EventWithApiKeyResponse(EventResponse):
    """Only used when creating a new event - includes the API key once."""
    api_key: str


class OrderCreate(BaseModel):
    order_text: str = Field(..., min_length=1, max_length=5000)
    first_name: str = Field(..., min_length=1, max_length=255)
    last_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr | None = None
    phone_number: str | None = Field(None, max_length=50)
    address_line_1: str = Field(..., min_length=1, max_length=255)
    address_line_2: str | None = Field(None, max_length=255)
    city: str = Field(..., min_length=1, max_length=255)
    state: str = Field(..., min_length=1, max_length=255)
    postal_code: str = Field(..., min_length=1, max_length=255)
    country: str = Field(..., min_length=1, max_length=255)
    order_notes: str | None = Field(None, max_length=1000)


class OrderResponse(BaseModel):
    order_id: str
    status: OrderStatus
    status_url: str
    created_at: datetime
    email_sent: bool = False

    class Config:
        from_attributes = True


class OrderStatusResponse(BaseModel):
    order_id: str
    status: OrderStatus
    tracking_code: str | None = None
    fulfillment_note: str | None = None
    created_at: datetime
    fulfilled_at: datetime | None = None
