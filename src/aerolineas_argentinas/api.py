"""Direct HTTP client for Aerolineas Argentinas flight offers."""
from __future__ import annotations

from datetime import date
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://api.aerolineas.com.ar/v1/flights/offers"
ANCILLARIES_URL = "https://api.aerolineas.com.ar/v2/checkout/ancillaries"
PASSENGERS_URL = "https://api.aerolineas.com.ar/v2/checkout/passengers"


def _headers(access_token: str) -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-AR",
        "Authorization": f"Bearer {access_token}",
        "Origin": "https://www.aerolineas.com.ar",
        "Referer": "https://www.aerolineas.com.ar/",
        "User-Agent": "Mozilla/5.0 (compatible; AerolineasFareResearch/0.1)",
        "X-Channel-Id": "WEB_AR",
    }


def fetch_offers(
    origin: str,
    destination: str,
    travel_date: date,
    access_token: str,
    *,
    flex_dates: bool = False,
    timeout: int = 30,
) -> dict:
    """Fetch one-way offers without starting a browser session."""
    query = urlencode({
        "adt": 1,
        "inf": 0,
        "chd": 0,
        "flexDates": str(flex_dates).lower(),
        "cabinClass": "Economy",
        "flightType": "ONE_WAY",
        "leg": f"{origin.upper()}-{destination.upper()}-{travel_date:%Y%m%d}",
    })
    request = Request(
        f"{API_URL}?{query}",
        headers=_headers(access_token),
    )
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def fetch_ancillaries(
    shopping_id: str,
    access_token: str,
    *,
    timeout: int = 30,
) -> dict:
    """Fetch ancillary offers for a shopping session."""
    query = urlencode({"shoppingId": shopping_id})
    request = Request(
        f"{ANCILLARIES_URL}?{query}",
        headers=_headers(access_token),
    )
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def submit_passenger(
    shopping_id: str,
    travel_date: date,
    access_token: str,
    *,
    recaptcha_token: str | None = None,
    timeout: int = 30,
) -> dict:
    """Register one fake passenger before requesting ancillaries."""
    payload = {
        "shoppingId": shopping_id,
        "passengersData": [{
            "passengerIndex": 1,
            "firstName": "Test",
            "lastName": "Pricing",
            "birthDate": "2002-05-03",
            "gender": "MALE",
            "redressNumber": "",
            "passengerType": "ADT",
            "document": {
                "documentType": "I",
                "documentNumber": "777777777",
                "nationality": "AR",
                "issuingCountry": "AR",
                "expirationDate": "2031-05-03",
            },
            "frequentFlyerInformation": None,
            "specialPreferences": None,
            "residentialAddress": None,
            "destinationAddress": None,
            "arrivalDate": travel_date.isoformat(),
        }],
        "contactInformation": {
            "phones": [{"type": "HOME", "areaCode": "11", "number": "99999999", "countryCode": "54"}],
            "emails": ["pricing.test@example.com"],
        },
        "emergencyContact": {"name": "", "country": "", "areaCode": "", "phone": "", "relationship": ""},
        "marketingEngagement": False,
    }
    headers = _headers(access_token) | {
        "Content-Type": "application/json",
        "X-Client-Platform": "web",
    }
    if recaptcha_token:
        headers["X-Recaptcha-Token"] = recaptcha_token
    request = Request(
        PASSENGERS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)
