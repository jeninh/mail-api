import pytest
from pydantic import ValidationError

from app.models import MailType
from app.schemas import CostCalculatorRequest, LetterCreate, OrderCreate


class TestLetterCreate:
    @pytest.fixture
    def valid_letter_data(self):
        return {
            "first_name": "John",
            "last_name": "Doe",
            "address_line_1": "123 Main St",
            "city": "Toronto",
            "state": "ON",
            "postal_code": "M5V 1A1",
            "country": "Canada",
            "mail_type": MailType.LETTERMAIL,
            "rubber_stamps": "stamp1",
        }

    def test_valid_lettermail_without_weight(self, valid_letter_data):
        letter = LetterCreate(**valid_letter_data)
        assert letter.first_name == "John"
        assert letter.weight_grams is None

    def test_valid_lettermail_with_weight(self, valid_letter_data):
        valid_letter_data["weight_grams"] = 50
        letter = LetterCreate(**valid_letter_data)
        assert letter.weight_grams == 50

    def test_bubble_packet_without_weight_allowed(self, valid_letter_data):
        valid_letter_data["mail_type"] = MailType.BUBBLE_PACKET
        letter = LetterCreate(**valid_letter_data)
        assert letter.weight_grams is None

    def test_parcel_without_weight_allowed(self, valid_letter_data):
        valid_letter_data["mail_type"] = MailType.PARCEL
        letter = LetterCreate(**valid_letter_data)
        assert letter.weight_grams is None

    def test_bubble_packet_with_weight_succeeds(self, valid_letter_data):
        valid_letter_data["mail_type"] = MailType.BUBBLE_PACKET
        valid_letter_data["weight_grams"] = 100
        letter = LetterCreate(**valid_letter_data)
        assert letter.weight_grams == 100

    def test_parcel_with_weight_succeeds(self, valid_letter_data):
        valid_letter_data["mail_type"] = MailType.PARCEL
        valid_letter_data["weight_grams"] = 500
        letter = LetterCreate(**valid_letter_data)
        assert letter.weight_grams == 500

    def test_first_name_min_length(self, valid_letter_data):
        valid_letter_data["first_name"] = ""
        with pytest.raises(ValidationError) as exc_info:
            LetterCreate(**valid_letter_data)
        assert "first_name" in str(exc_info.value)

    def test_first_name_max_length(self, valid_letter_data):
        valid_letter_data["first_name"] = "a" * 256
        with pytest.raises(ValidationError) as exc_info:
            LetterCreate(**valid_letter_data)
        assert "first_name" in str(exc_info.value)

    def test_rubber_stamps_min_length(self, valid_letter_data):
        valid_letter_data["rubber_stamps"] = ""
        with pytest.raises(ValidationError) as exc_info:
            LetterCreate(**valid_letter_data)
        assert "rubber_stamps" in str(exc_info.value)

    def test_valid_recipient_email(self, valid_letter_data):
        valid_letter_data["recipient_email"] = "test@example.com"
        letter = LetterCreate(**valid_letter_data)
        assert letter.recipient_email == "test@example.com"

    def test_invalid_recipient_email(self, valid_letter_data):
        valid_letter_data["recipient_email"] = "not-an-email"
        with pytest.raises(ValidationError) as exc_info:
            LetterCreate(**valid_letter_data)
        assert "recipient_email" in str(exc_info.value)

    def test_weight_grams_must_be_positive(self, valid_letter_data):
        valid_letter_data["weight_grams"] = 0
        with pytest.raises(ValidationError) as exc_info:
            LetterCreate(**valid_letter_data)
        assert "weight_grams" in str(exc_info.value)


class TestCostCalculatorRequest:
    def test_valid_request(self):
        request = CostCalculatorRequest(
            country="Canada",
            mail_type=MailType.LETTERMAIL,
        )
        assert request.country == "Canada"
        assert request.mail_type == MailType.LETTERMAIL
        assert request.weight_grams is None

    def test_valid_request_with_weight(self):
        request = CostCalculatorRequest(
            country="USA",
            mail_type=MailType.PARCEL,
            weight_grams=250,
        )
        assert request.weight_grams == 250


class TestOrderCreate:
    @pytest.fixture
    def valid_order_data(self):
        return {
            "order_text": "Test order",
            "first_name": "Jane",
            "last_name": "Smith",
            "address_line_1": "456 Oak Ave",
            "city": "Vancouver",
            "state": "BC",
            "postal_code": "V6B 1A1",
            "country": "Canada",
        }

    def test_valid_order(self, valid_order_data):
        order = OrderCreate(**valid_order_data)
        assert order.first_name == "Jane"
        assert order.email is None

    def test_order_text_min_length(self, valid_order_data):
        valid_order_data["order_text"] = ""
        with pytest.raises(ValidationError) as exc_info:
            OrderCreate(**valid_order_data)
        assert "order_text" in str(exc_info.value)

    def test_order_text_max_length(self, valid_order_data):
        valid_order_data["order_text"] = "a" * 5001
        with pytest.raises(ValidationError) as exc_info:
            OrderCreate(**valid_order_data)
        assert "order_text" in str(exc_info.value)

    def test_first_name_required(self, valid_order_data):
        del valid_order_data["first_name"]
        with pytest.raises(ValidationError) as exc_info:
            OrderCreate(**valid_order_data)
        assert "first_name" in str(exc_info.value)

    def test_valid_email(self, valid_order_data):
        valid_order_data["email"] = "jane@example.com"
        order = OrderCreate(**valid_order_data)
        assert order.email == "jane@example.com"

    def test_invalid_email(self, valid_order_data):
        valid_order_data["email"] = "invalid-email"
        with pytest.raises(ValidationError) as exc_info:
            OrderCreate(**valid_order_data)
        assert "email" in str(exc_info.value)

    def test_address_line_2_optional(self, valid_order_data):
        order = OrderCreate(**valid_order_data)
        assert order.address_line_2 is None

    def test_address_line_2_max_length(self, valid_order_data):
        valid_order_data["address_line_2"] = "a" * 256
        with pytest.raises(ValidationError) as exc_info:
            OrderCreate(**valid_order_data)
        assert "address_line_2" in str(exc_info.value)

    def test_order_notes_optional(self, valid_order_data):
        order = OrderCreate(**valid_order_data)
        assert order.order_notes is None

    def test_order_notes_valid(self, valid_order_data):
        valid_order_data["order_notes"] = "Please leave at front door"
        order = OrderCreate(**valid_order_data)
        assert order.order_notes == "Please leave at front door"

    def test_order_notes_max_length_valid(self, valid_order_data):
        valid_order_data["order_notes"] = "a" * 1000
        order = OrderCreate(**valid_order_data)
        assert len(order.order_notes) == 1000

    def test_order_notes_max_length_exceeded(self, valid_order_data):
        valid_order_data["order_notes"] = "a" * 1001
        with pytest.raises(ValidationError) as exc_info:
            OrderCreate(**valid_order_data)
        assert "order_notes" in str(exc_info.value)

    def test_phone_number_optional(self, valid_order_data):
        order = OrderCreate(**valid_order_data)
        assert order.phone_number is None

    def test_phone_number_valid(self, valid_order_data):
        valid_order_data["phone_number"] = "+1-555-123-4567"
        order = OrderCreate(**valid_order_data)
        assert order.phone_number == "+1-555-123-4567"

    def test_phone_number_max_length_valid(self, valid_order_data):
        valid_order_data["phone_number"] = "a" * 50
        order = OrderCreate(**valid_order_data)
        assert len(order.phone_number) == 50

    def test_phone_number_max_length_exceeded(self, valid_order_data):
        valid_order_data["phone_number"] = "a" * 51
        with pytest.raises(ValidationError) as exc_info:
            OrderCreate(**valid_order_data)
        assert "phone_number" in str(exc_info.value)
