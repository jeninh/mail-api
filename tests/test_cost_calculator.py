import pytest

from app.cost_calculator import (
    CostCalculationError,
    ParcelQuoteRequired,
    calculate_bubble_packet_cost,
    calculate_cost,
    calculate_lettermail_cost,
    cents_to_usd,
)
from app.models import MailType


class TestLettermailCost:
    def test_canada(self):
        assert calculate_lettermail_cost("Canada") == 175
        assert calculate_lettermail_cost("canada") == 175
        assert calculate_lettermail_cost("CANADA") == 175

    def test_united_states(self):
        assert calculate_lettermail_cost("United States") == 200
        assert calculate_lettermail_cost("united states") == 200
        assert calculate_lettermail_cost("USA") == 200
        assert calculate_lettermail_cost("US") == 200

    def test_international(self):
        assert calculate_lettermail_cost("Germany") == 350
        assert calculate_lettermail_cost("Japan") == 350
        assert calculate_lettermail_cost("Australia") == 350


class TestBubblePacketCost:
    def test_canada_weight_tiers(self):
        assert calculate_bubble_packet_cost("Canada", 50) == 311
        assert calculate_bubble_packet_cost("Canada", 100) == 311
        assert calculate_bubble_packet_cost("Canada", 150) == 451
        assert calculate_bubble_packet_cost("Canada", 200) == 451
        assert calculate_bubble_packet_cost("Canada", 250) == 591
        assert calculate_bubble_packet_cost("Canada", 350) == 662
        assert calculate_bubble_packet_cost("Canada", 450) == 705
        assert calculate_bubble_packet_cost("Canada", 500) == 705

    def test_us_weight_tiers(self):
        assert calculate_bubble_packet_cost("United States", 50) == 451
        assert calculate_bubble_packet_cost("United States", 150) == 716
        assert calculate_bubble_packet_cost("United States", 300) == 1338

    def test_international_weight_tiers(self):
        assert calculate_bubble_packet_cost("Germany", 50) == 808
        assert calculate_bubble_packet_cost("Germany", 150) == 1338
        assert calculate_bubble_packet_cost("Germany", 300) == 2580

    def test_exceeds_weight_limit(self):
        with pytest.raises(CostCalculationError) as exc_info:
            calculate_bubble_packet_cost("Canada", 501)
        assert "exceeds 500g" in str(exc_info.value)


class TestCalculateCost:
    def test_lettermail(self):
        cost = calculate_cost(MailType.LETTERMAIL, "Canada")
        assert cost == 175

    def test_bubble_packet(self):
        cost = calculate_cost(MailType.BUBBLE_PACKET, "Canada", 150)
        assert cost == 451

    def test_bubble_packet_requires_weight(self):
        with pytest.raises(CostCalculationError) as exc_info:
            calculate_cost(MailType.BUBBLE_PACKET, "Canada")
        assert "Weight is required" in str(exc_info.value)

    def test_parcel_raises_quote_required(self):
        with pytest.raises(ParcelQuoteRequired):
            calculate_cost(MailType.PARCEL, "Canada", 1000)


class TestCentsToUsd:
    def test_conversion(self):
        assert cents_to_usd(119) == 1.19
        assert cents_to_usd(1000) == 10.00
        assert cents_to_usd(2485) == 24.85
        assert cents_to_usd(0) == 0.00
