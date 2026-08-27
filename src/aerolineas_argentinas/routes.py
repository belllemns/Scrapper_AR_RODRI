"""Route and date helpers."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
import re


def parse_route(value: str) -> tuple[str, str]:
    compact = re.sub(r"[^A-Za-z]", "", value).upper()
    if len(compact) != 6:
        raise ValueError("route debe tener 6 letras IATA")
    return compact[:3], compact[3:]


def add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year, month = value.year + month // 12, month % 12 + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def offers_url(
    origin: str, destination: str, travel_date: date, *, flex: bool, shopping_id: str | None = None
) -> str:
    url = (
        "https://www.aerolineas.com.ar/flights-offers?"
        f"adt=1&inf=0&chd=0&flexDates={'true' if flex else 'false'}&"
        f"cabinClass=Economy&flightType=ONE_WAY&leg={origin}-{destination}-{travel_date:%Y%m%d}"
    )
    return f"{url}&shoppingId={shopping_id}" if shopping_id else url
