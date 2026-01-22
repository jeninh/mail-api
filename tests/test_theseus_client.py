import pytest

from app.theseus_client import TheseusAPIError, TheseusClient


class TestTheseusAPIError:
    def test_stores_message(self):
        error = TheseusAPIError("Test error message")
        assert error.message == "Test error message"

    def test_stores_status_code(self):
        error = TheseusAPIError("Test error", status_code=404)
        assert error.status_code == 404

    def test_status_code_defaults_to_none(self):
        error = TheseusAPIError("Test error")
        assert error.status_code is None

    def test_inherits_from_exception(self):
        error = TheseusAPIError("Test error", status_code=500)
        assert isinstance(error, Exception)
        assert str(error) == "Test error"


class TestTheseusClientURLHelpers:
    @pytest.fixture
    def client(self):
        return TheseusClient()

    def test_get_letter_url(self, client):
        url = client.get_letter_url("ltr!32jhyrnk")
        assert url == "https://mail.hackclub.com/back_office/letters/ltr!32jhyrnk"

    def test_get_letter_url_with_different_id(self, client):
        url = client.get_letter_url("abc123")
        assert url == "https://mail.hackclub.com/back_office/letters/abc123"

    def test_get_public_letter_url(self, client):
        url = client.get_public_letter_url("ltr!32jhyrnk")
        assert url == "https://hack.club/ltr!32jhyrnk"

    def test_get_public_letter_url_with_different_id(self, client):
        url = client.get_public_letter_url("abc123")
        assert url == "https://hack.club/abc123"

    def test_get_queue_url(self, client):
        url = client.get_queue_url("hcb_stickers")
        assert url == "https://mail.hackclub.com/back_office/letter/queues/hcb_stickers"

    def test_get_queue_url_with_different_name(self, client):
        url = client.get_queue_url("sprig_postcards")
        assert url == "https://mail.hackclub.com/back_office/letter/queues/sprig_postcards"
