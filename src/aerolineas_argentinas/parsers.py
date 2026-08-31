"""Pure parsers for Aerolineas Argentinas offer responses."""
from __future__ import annotations

from typing import Any


def _money(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _offer_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    branded = payload.get("brandedOffers", {})
    groups = branded.get("0", []) if isinstance(branded, dict) else branded
    return [offer for group in groups for offer in group.get("offers", [])]


def _net_price(offer: dict[str, Any]) -> tuple[float | None, dict[str, float]]:
    fare = offer.get("fare", {})
    base = _money(fare.get("baseFare"))
    surcharges = _money(fare.get("surcharges"))
    if surcharges is None:
        surcharges = _money(fare.get("charges"))
    # The checkout label "Cargo" is represented by surcharges in the offer detail.
    net = base + surcharges if base is not None and surcharges is not None else None
    return net, {"base_fare": base, "surcharges": surcharges}


def parse_offers(payload: dict[str, Any], requested_class: str) -> list[dict[str, Any]]:
    """Return offers for one booking class, preserving explicit fare fields."""
    rows = []
    metadata = payload.get("searchMetadata", {})
    for offer in _offer_rows(payload):
        if str(offer.get("bookingClass", "")).upper() != requested_class.upper():
            continue
        fare = offer.get("fare", {})
        net, parts = _net_price(offer)
        rows.append({
            "booking_class": requested_class.upper(),
            "offer_id": offer.get("offerId"),
            "brand_id": offer.get("brandId") or offer.get("brand", {}).get("id"),
            "fare_basis": offer.get("fareBasis"),
            "currency": metadata.get("currency", "ARS"),
            "base_fare": parts["base_fare"],
            "surcharges": parts["surcharges"],
            "price_without_taxes": net,
            "taxes": _money(fare.get("taxes")),
            "price_total": _money(fare.get("total")),
        })
    return rows


def select_offer(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Select Base E first and Base N second; never substitute another brand."""
    for booking_class in ("E", "N"):
        matches = parse_offers(payload, booking_class)
        base = next((row for row in matches if row.get("brand_id") == "EB"), None)
        if base:
            return base
    return None


def calendar_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten calendar days that expose a booking class and an offer."""
    calendar = payload.get("calendarOffers", {})
    values = [item for items in calendar.values() for item in items] if isinstance(calendar, dict) else []
    rows = []
    for item in values:
        detail = item.get("offerDetails") or {}
        booking_class = str(detail.get("bookingClass", "")).upper()
        if not booking_class or item.get("soldOut"):
            continue
        fare = detail.get("fare", {})
        rows.append({
            "date": item.get("departure"),
            "booking_class": booking_class,
            "base_fare": _money(fare.get("baseFare")),
            "calendar_total": _money(fare.get("total")),
            "flight_number": (item.get("leg", {}).get("segments") or [{}])[0].get("flightNumber"),
        })
    return rows


def select_offer_group(
    payload: dict[str, Any],
    requested_class: str | None = None,
    flight_number: int | None = None,
) -> tuple[dict[str, Any], int, int] | None:
    """Return a Base E/N offer, optionally matching the calendar selection."""
    branded = payload.get("brandedOffers", {}).get("0", [])
    requested_classes = (requested_class.upper(),) if requested_class else ("E", "N")
    for booking_class in requested_classes:
        for group_index, group in enumerate(branded):
            segment = ((group.get("legs") or [{}])[0].get("segments") or [{}])[0]
            if (flight_number is not None
                    and str(segment.get("flightNumber")) != str(flight_number)):
                continue
            for offer_index, offer in enumerate(group.get("offers", [])):
                brand_id = offer.get("brandId") or offer.get("brand", {}).get("id")
                if (brand_id == "EB"
                        and str(offer.get("bookingClass", "")).upper() == booking_class
                        and str(offer.get("cabinClass", "")).lower() == "economy"):
                    group_row = dict(group)
                    group_row["offers"] = list(group.get("offers", []))
                    return group_row, group_index, offer_index
    return None


def selected_offer_details(payload: dict[str, Any], offer_id: str) -> dict[str, Any]:
    """Resolve the selected offer ID to its fare class, flight, and brand totals."""
    branded = payload.get("brandedOffers", {}).get("0", [])
    for group in branded:
        offers = group.get("offers", [])
        selected = next(
            (offer for offer in offers if str(offer.get("offerId")) == str(offer_id)),
            None,
        )
        if selected is None:
            continue
        booking_class = selected.get("bookingClass")
        same_class = [
            offer for offer in offers
            if offer.get("bookingClass") == booking_class
        ]
        totals = {
            (offer.get("brand", {}).get("id") or offer.get("brandId")):
            _money(offer.get("fare", {}).get("total"))
            for offer in same_class
        }
        leg = (group.get("legs") or [{}])[0]
        segment = (leg.get("segments") or [{}])[0]
        brand = selected.get("brand", {})
        return {
            "selected_offer_id": str(offer_id),
            "booking_class": booking_class,
            "fare_basis": selected.get("fareBasis"),
            "brand_id": brand.get("id") or selected.get("brandId"),
            "brand_name": brand.get("name"),
            "flight_number": segment.get("flightNumber"),
            "departure_datetime": segment.get("departure"),
            "arrival_datetime": segment.get("arrival"),
            "stops": leg.get("stops"),
            "duration_minutes": leg.get("totalDuration"),
            "currency": payload.get("searchMetadata", {}).get("currency", "ARS"),
            "base_total": totals.get("EB"),
            "plus_total": totals.get("EP"),
            "flex_total": totals.get("EF"),
        }
    return {}


def parse_checkout_detail(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract the displayed net ticket price from the selected-offer detail."""
    breakdown = payload.get("productBreakdown", {}).get("airBreakdown", {})
    base = _money(breakdown.get("baseFare", {}).get("price"))
    taxes = _money(breakdown.get("taxes", {}).get("price"))
    surcharges = _money(breakdown.get("surcharges", {}).get("price"))
    return {
        "base_fare": base,
        "taxes": taxes,
        "surcharges": surcharges,
        "price_without_taxes": base + surcharges if base is not None and surcharges is not None else None,
        "price_total": _money(breakdown.get("total")) or _money(payload.get("total")),
        "currency": payload.get("revenueData", {}).get("currency", "ARS"),
        "flight_number": (payload.get("summaryMetadata", {}).get("citySegments") or [{}])[0].get("flightNumber"),
        "departure_datetime": (payload.get("summaryMetadata", {}).get("citySegments") or [{}])[0].get("departureDate"),
        "arrival_datetime": (payload.get("summaryMetadata", {}).get("citySegments") or [{}])[0].get("arrivalDate"),
        "stops": max(0, len(payload.get("flightInformation", {}).get("legs", [{}])[0].get("segments", [])) - 1),
        "duration_minutes": (payload.get("flightInformation", {}).get("legs") or [{}])[0].get("totalDuration"),
    }


def parse_ancillaries(payload: dict[str, Any]) -> dict[str, Any]:
    """Flatten the listed price for each baggage group."""
    result: dict[str, Any] = {
        "special_baggage_price": None,
        "checked_baggage_price": None,
        "checked_baggage_additional_price": None,
        "hand_baggage_price": None,
    }
    for group in payload.get("ancillaryGroups", []):
        prices = [
            _money(ancillary.get("price"))
            for passenger in group.get("ancillaryPassengers", [])
            for leg in passenger.get("ancillaryLegs", [])
            for ancillary in leg.get("ancillaries", [])
            if _money(ancillary.get("price")) is not None
        ]
        if not prices:
            continue
        if group.get("groupCode") == "SP":
            result["special_baggage_price"] = min(prices)
        elif group.get("groupCode") == "BG":
            result["checked_baggage_price"] = prices[0]
            result["checked_baggage_additional_price"] = prices[1] if len(prices) > 1 else None
        elif group.get("groupCode") == "EM":
            result["hand_baggage_price"] = min(prices)
    return result
