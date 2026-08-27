"""Direct HTTP client for Aerolineas Argentinas flight offers."""
from __future__ import annotations

from datetime import date
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://api.aerolineas.com.ar/v1/flights/offers"


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
        headers={
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-AR",
            "Authorization": f"Bearer {access_token}",
            "Referer": "https://www.aerolineas.com.ar/",
            "User-Agent": "Mozilla/5.0 (compatible; AerolineasFareResearch/0.1)",
            "X-Channel-Id": "WEB_AR",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)
