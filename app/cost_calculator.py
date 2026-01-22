from app.models import MailType


class CostCalculationError(Exception):
    pass


class ParcelQuoteRequired(Exception):
    pass


def calculate_lettermail_cost(country: str) -> int:
    """
    Returns cost in cents USD for lettermail.

    Limitations:
    - Weight: Up to 30g
    - Dimensions: 245mm × 156mm × 5mm (9.6" × 6.1" × 0.2")
    """
    country_lower = country.lower().strip()

    if country_lower == "canada":
        return 175  # $1.75 USD
    elif country_lower in ["united states", "usa", "us", "united states of america"]:
        return 200  # $2.00 USD
    else:
        return 350  # $3.50 USD (International)


def calculate_bubble_packet_cost(country: str, weight_grams: int) -> int:
    """
    Returns cost in cents USD for bubble packets.

    Dimensions: 380mm × 270mm × 20mm (14.9" × 10.6" × 0.8")
    Max weight: 500g
    """
    if weight_grams > 500:
        raise CostCalculationError(
            "Weight exceeds 500g for bubble packets. A parcel is needed. "
            "Please DM @jenin on Slack for rates."
        )

    country_lower = country.lower().strip()

    if country_lower == "canada":
        if weight_grams <= 100:
            return 311
        elif weight_grams <= 200:
            return 451
        elif weight_grams <= 300:
            return 591
        elif weight_grams <= 400:
            return 662
        else:  # <= 500
            return 705

    elif country_lower in ["united states", "usa", "us", "united states of america"]:
        if weight_grams <= 100:
            return 451
        elif weight_grams <= 200:
            return 716
        else:  # <= 500
            return 1338

    else:  # International
        if weight_grams <= 100:
            return 808
        elif weight_grams <= 200:
            return 1338
        else:  # <= 500
            return 2580


def calculate_parcel_cost(weight_grams: int, country: str) -> int:
    """
    Parcels require a custom quote from Hermes.
    Raises ParcelQuoteRequired exception.
    """
    raise ParcelQuoteRequired(
        f"Parcel shipping requires a custom quote. "
        f"Weight: {weight_grams}g, Destination: {country}. "
        f"Please DM @jenin on Slack."
    )


def calculate_cost(mail_type: MailType, country: str, weight_grams: int | None = None) -> int:
    """
    Main cost calculation function.
    Returns cost in cents USD.

    Args:
        mail_type: Type of mail (lettermail, bubble_packet, parcel)
        country: Destination country
        weight_grams: Weight in grams (required for bubble_packet and parcel)

    Returns:
        Cost in cents

    Raises:
        CostCalculationError: For invalid inputs
        ParcelQuoteRequired: When parcel requires custom quote
    """
    if mail_type == MailType.LETTERMAIL:
        return calculate_lettermail_cost(country)

    elif mail_type == MailType.BUBBLE_PACKET:
        if weight_grams is None:
            raise CostCalculationError("Weight is required for bubble packets")
        return calculate_bubble_packet_cost(country, weight_grams)

    elif mail_type == MailType.PARCEL:
        if weight_grams is None:
            raise CostCalculationError("Weight is required for parcels")
        return calculate_parcel_cost(weight_grams, country)

    else:
        raise CostCalculationError(f"Unknown mail type: {mail_type}")


def cents_to_usd(cents: int) -> float:
    """Convert cents to USD with 2 decimal places."""
    return round(cents / 100, 2)


def get_stamp_region(country: str) -> str:
    """
    Returns the stamp region for a given country.

    Returns:
        'CA' for Canada
        'US' for United States
        'INT' for International
    """
    country_lower = country.lower().strip()

    if country_lower == "canada":
        return "CA"
    elif country_lower in ["united states", "usa", "us", "united states of america"]:
        return "US"
    else:
        return "INT"


def get_mail_type_limits() -> dict:
    """Returns information about mail type limits for documentation."""
    return {
        "lettermail": {
            "max_weight_grams": 30,
            "max_dimensions_mm": "245 × 156 × 5",
            "max_dimensions_inches": "9.6 × 6.1 × 0.2"
        },
        "bubble_packet": {
            "max_weight_grams": 500,
            "max_dimensions_mm": "380 × 270 × 20",
            "max_dimensions_inches": "14.9 × 10.6 × 0.8"
        },
        "parcel": {
            "note": "Custom quote required - contact @jenin"
        }
    }
