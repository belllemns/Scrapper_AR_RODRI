"""Fast Aerolineas Argentinas fare search using the flexible-date calendar."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from pathlib import Path
import time

import pyarrow as pa
import pyarrow.parquet as pq

from aerolineas_argentinas.browser import capture_api_responses, launch_driver
from aerolineas_argentinas.parsers import (
    calendar_candidates,
    parse_ancillaries,
    parse_checkout_detail,
    select_offer_group,
)
from aerolineas_argentinas.routes import add_months, offers_url, parse_route


ROUTES = "BRCBUE BRCMDZ BUECOR BUECPC BUECRD BUEFTE BUEIGR BUEMDZ BUENQN BUEJUJ BUESLA BUETUC BUEUSH MDZSLA NQNSLA BUERES BUEPSS BUESDE BUEUAQ BUEREL".split()


def month_starts(start: date, end: date) -> list[date]:
    current = start.replace(day=1)
    result = []
    while current <= end:
        result.append(current)
        current = add_months(current, 1)
    return result


def _empty_fare() -> dict[str, float | None]:
    return {"base_fare": None, "surcharges": None, "price_without_taxes": None,
            "taxes": None, "price_total": None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--routes", nargs="*", default=ROUTES)
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--wait-seconds", type=int, default=3)
    parser.add_argument("--candidates-per-route", type=int, default=5)
    parser.add_argument("--profile-dir", default="aerolineas-profile")
    parser.add_argument("--output", default=str(Path.home() / "Downloads" / "aerolineas_argentinas_fares.parquet"))
    args = parser.parse_args()

    today = date.today()
    start = args.start_date or add_months(today, 1)
    end = args.end_date or add_months(today, 7)
    driver = launch_driver(args.profile_dir)
    results = []

    def click_fare(group_index: int, offer_index: int) -> None:
        script = """
        const [group, offer] = arguments;
        [...document.querySelectorAll('button')]
          .find(x => x.innerText.trim() === 'Aceptar solo las esenciales')?.click();
        const cards = [...document.querySelectorAll('button')]
          .filter(x => x.className.includes('FareContainer'));
        const index = group * 5 + offer;
        if (cards.length <= index) {
          const more = [...document.querySelectorAll('button')]
            .find(x => x.innerText.includes('Mostrar más vuelos'));
          if (more) { more.click(); return false; }
          throw new Error(`No se encontró card ${group}/${offer}`);
        }
        cards[index].click();
        return true;
        """
        for _ in range(10):
            if driver.execute_script(script, group_index, offer_index):
                return
            time.sleep(1)

    def complete_passenger() -> None:
        script = """
        const setValue = (selectors, value) => {
          const el = selectors.map(s => document.querySelector(s)).find(Boolean);
          if (!el) return;
          const setter = Object.getOwnPropertyDescriptor(el.__proto__, 'value')?.set;
          if (setter) setter.call(el, value); else el.value = value;
          el.dispatchEvent(new Event('input', {bubbles:true}));
          el.dispatchEvent(new Event('change', {bubbles:true}));
        };
        setValue(['input[name*=firstName i]', 'input[id*=firstName i]'], 'Test');
        setValue(['input[name*=lastName i]', 'input[id*=lastName i]'], 'Pricing');
        setValue(['input[name*=birthDate i]', 'input[id*=birthDate i]'], '03/05/2002');
        setValue(['input[name*=documentNumber i]', 'input[id*=documentNumber i]'], '777777777');
        setValue(['input[type=email]', 'input[name*=email i]'], 'pricing.test@example.com');
        const next = [...document.querySelectorAll('button')]
          .find(x => /^(Continuar|Siguiente)$/i.test(x.innerText.trim()));
        if (next) next.click();
        """
        driver.execute_script(script)

    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.get("https://www.aerolineas.com.ar/")
        for route in args.routes:
            origin, destination = parse_route(route)
            candidates = []
            for anchor in month_starts(start, end):
                driver.get(offers_url(origin, destination, anchor, flex=True))
                time.sleep(args.wait_seconds)
                responses = capture_api_responses(driver)
                if not any(item.get("body", {}).get("calendarOffers") for item in responses
                           if isinstance(item.get("body"), dict)):
                    time.sleep(1)
                    responses.extend(capture_api_responses(driver))
                payloads = [item["body"] for item in responses
                            if isinstance(item.get("body"), dict)]
                for payload in payloads:
                    for candidate in calendar_candidates(payload):
                        candidate["shopping_id"] = payload.get("searchMetadata", {}).get("shoppingId")
                        if start.isoformat() <= candidate["date"] <= end.isoformat():
                            candidates.append(candidate)
            candidates.sort(key=lambda item: item.get("base_fare") or float("inf"))
            found = None
            for candidate in candidates[:args.candidates_per_route]:
                travel_date = date.fromisoformat(candidate["date"])
                driver.get(offers_url(origin, destination, travel_date, flex=False,
                                       shopping_id=candidate.get("shopping_id")))
                time.sleep(args.wait_seconds)
                payloads = [item["body"] for item in capture_api_responses(driver)
                            if isinstance(item.get("body"), dict)]
                for payload in reversed(payloads):
                    group_info = select_offer_group(payload)
                    if not group_info:
                        continue
                    group, group_index, selected_index = group_info
                    offers = group.get("offers", [])
                    selected = offers[selected_index]
                    click_fare(group_index, selected_index)
                    time.sleep(args.wait_seconds)
                    detail_responses = capture_api_responses(driver)
                    detail = next((item["body"] for item in detail_responses
                                   if isinstance(item.get("body"), dict)
                                   and item["body"].get("productBreakdown")), None)
                    if detail is None:
                        time.sleep(1)
                        detail = next((item["body"] for item in capture_api_responses(driver)
                                       if isinstance(item.get("body"), dict)
                                       and item["body"].get("productBreakdown")), None)
                    base_detail = parse_checkout_detail(detail) if detail else {}
                    complete_passenger()
                    time.sleep(args.wait_seconds)
                    ancillary_responses = capture_api_responses(driver)
                    ancillary = next((item["body"] for item in ancillary_responses
                                      if isinstance(item.get("body"), dict)
                                      and item["body"].get("ancillaryGroups")), None)
                    if ancillary is None:
                        time.sleep(1)
                        ancillary = next((item["body"] for item in capture_api_responses(driver)
                                          if isinstance(item.get("body"), dict)
                                          and item["body"].get("ancillaryGroups")), None)
                    ancillary_detail = parse_ancillaries(ancillary) if ancillary else {}
                    fares = {}
                    for label, brand_ids in (("base", {"EB"}), ("plus", {"EP"}), ("flex", {"EF"})):
                        offer = next((item for item in offers
                                      if item.get("brand", {}).get("id") in brand_ids), None)
                        values = _empty_fare()
                        if offer:
                            fare = offer.get("fare", {})
                            values.update({"base_fare": fare.get("baseFare"),
                                           "taxes": fare.get("taxes"),
                                           "price_total": fare.get("total")})
                            if base_detail.get("surcharges") is not None:
                                values["surcharges"] = base_detail["surcharges"]
                                values["price_without_taxes"] = values["base_fare"] + values["surcharges"]
                        fares[label] = values
                    found = {
                        "booking_class": selected.get("bookingClass"),
                        "fare_basis": selected.get("fareBasis"),
                        "brand_id": selected.get("brand", {}).get("id"),
                        "flight_number": (group.get("legs", [{}])[0].get("segments") or [{}])[0].get("flightNumber"),
                        "departure_datetime": (group.get("legs", [{}])[0].get("segments") or [{}])[0].get("departure"),
                        "arrival_datetime": (group.get("legs", [{}])[0].get("segments") or [{}])[0].get("arrival"),
                        "stops": group.get("legs", [{}])[0].get("stops"),
                        "duration_minutes": group.get("legs", [{}])[0].get("totalDuration"),
                        "currency": payload.get("searchMetadata", {}).get("currency", "ARS"),
                        "base_without_taxes": fares["base"]["price_without_taxes"],
                        "plus_without_taxes": fares["plus"]["price_without_taxes"],
                        "flex_without_taxes": fares["flex"]["price_without_taxes"],
                        "base_total": fares["base"]["price_total"],
                        "plus_total": fares["plus"]["price_total"],
                        "flex_total": fares["flex"]["price_total"],
                        "taxes": base_detail.get("taxes"),
                        "surcharges": base_detail.get("surcharges"),
                        "special_baggage_price": ancillary_detail.get("special_baggage_price"),
                        "checked_baggage_price": ancillary_detail.get("checked_baggage_price"),
                        "checked_baggage_additional_price": ancillary_detail.get("checked_baggage_additional_price"),
                        "hand_baggage_price": ancillary_detail.get("hand_baggage_price"),
                    }
                    break
                if found:
                    break
            row = {"route": route, "origin": origin, "destination": destination,
                   "requested_start_date": start.isoformat(),
                   "found_date": candidate["date"] if found else None,
                   "status": "ok" if found else "not_found",
                   "calendar_candidates": len(candidates),
                   "run_timestamp_utc": datetime.now(timezone.utc).isoformat()}
            if found:
                row.update(found)
            else:
                row.update({key: None for key in (
                    "booking_class", "fare_basis", "brand_id", "flight_number",
                    "departure_datetime", "arrival_datetime", "stops", "duration_minutes",
                    "currency", "base_without_taxes", "plus_without_taxes", "flex_without_taxes",
                    "base_total", "plus_total", "flex_total", "taxes", "surcharges",
                    "special_baggage_price", "checked_baggage_price",
                    "checked_baggage_additional_price", "hand_baggage_price")})
            results.append(row)
            print(route, row["status"], row.get("found_date"), row.get("booking_class"))
    finally:
        driver.quit()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(results), output)
    print(f"parquet={output}")
    print(f"rows={len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
