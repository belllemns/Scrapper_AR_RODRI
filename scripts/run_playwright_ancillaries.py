"""Run one visible-browser search through ancillary price retrieval."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import time

from playwright.sync_api import Page, sync_playwright

from aerolineas_argentinas.parsers import (
    parse_ancillaries,
    select_offer_group,
    selected_offer_details,
)
from aerolineas_argentinas.routes import offers_url


def select_react_control(page: Page, control, value: str) -> None:
    control.click(force=True)
    control.fill(value)
    page.wait_for_timeout(200)
    page.locator("[role='option']").filter(
        has_text=re.compile(rf"^{re.escape(value)}(?:\s|$)", re.IGNORECASE)
    ).first.click()


def select_react_option(page: Page, index: int, value: str) -> None:
    select_react_control(
        page,
        page.locator("input[id^='react-select-']").nth(index),
        value,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="BRC")
    parser.add_argument("--destination", default="BUE")
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--output", default=str(Path.home() / "Downloads" / "aerolineas_playwright_ancillaries.json"))
    parser.add_argument("--timeout-seconds", type=int, default=45)
    args = parser.parse_args()

    started = time.perf_counter()
    result = {
        "route": f"{args.origin.upper()}{args.destination.upper()}",
        "date": args.date.isoformat(),
        "status": "error",
        "passengers_status": None,
        "ancillaries_status": None,
        "ancillaries": None,
        "selected_offer_id": None,
        "booking_class": None,
        "fare_basis": None,
        "brand_id": None,
        "brand_name": None,
        "flight_number": None,
        "departure_datetime": None,
        "arrival_datetime": None,
        "stops": None,
        "duration_minutes": None,
        "currency": None,
        "base_total": None,
        "plus_total": None,
        "flex_total": None,
        "error": None,
        "final_url": None,
        "page_title": None,
        "page_text_excerpt": None,
        "checkout_refreshed": False,
        "network_errors": [],
        "page_errors": [],
        "validation_messages": [],
        "selected_values": {},
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    ancillary_payload = None
    offers_payload = None
    selected_offer_id = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(locale="es-AR", viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.set_default_timeout(args.timeout_seconds * 1000)

        def capture_response(response) -> None:
            nonlocal ancillary_payload, offers_payload
            if "api.aerolineas.com.ar" in response.url and response.status >= 400:
                result["network_errors"].append({
                    "method": response.request.method,
                    "status": response.status,
                    "url": response.url,
                })
            if ("/v1/flights/offers" in response.url
                    and response.request.method == "GET" and response.ok):
                try:
                    payload = response.json()
                    if payload.get("brandedOffers"):
                        offers_payload = payload
                except Exception:
                    pass
            if "/v2/checkout/passengers" in response.url and response.request.method == "POST":
                result["passengers_status"] = response.status
            if "/v2/checkout/ancillaries" in response.url:
                result["ancillaries_status"] = response.status
                if response.ok:
                    try:
                        ancillary_payload = response.json()
                    except Exception:
                        pass

        def capture_request(request) -> None:
            nonlocal selected_offer_id
            if "/v1/flights/offers" not in request.url or request.method != "POST":
                return
            try:
                selected = json.loads(request.post_data or "{}").get("selectedFlights", [])
                if selected:
                    selected_offer_id = str(selected[0])
            except (TypeError, ValueError):
                pass

        page.on("request", capture_request)
        page.on("response", capture_response)
        page.on("pageerror", lambda error: result["page_errors"].append(str(error)))
        try:
            page.goto(
                offers_url(args.origin, args.destination, args.date, flex=False),
                wait_until="domcontentloaded",
            )
            if page.title() == "403 Forbidden":
                result.update(status="security_blocked", error="initial_request_403")
            else:
                offers_deadline = time.monotonic() + args.timeout_seconds
                while offers_payload is None and time.monotonic() < offers_deadline:
                    page.wait_for_timeout(500)
                if offers_payload is None:
                    result["error"] = "offers_response_not_received"
                    raise RuntimeError("offers response not received")
                group_info = select_offer_group(offers_payload)
                if group_info is None:
                    result["error"] = "no_e_n_offer_for_exact_date"
                    raise RuntimeError("no E/N offer for exact date")
                _, group_index, offer_index = group_info

                cookie_button = page.get_by_role("button", name="Aceptar solo las esenciales")
                if cookie_button.count():
                    cookie_button.last.click(force=True)
                    page.wait_for_timeout(500)

                fare_index = group_index * 5 + offer_index
                fare_cards = page.locator("button[class*='FareContainer']")
                render_deadline = time.monotonic() + args.timeout_seconds
                while fare_cards.count() <= fare_index and time.monotonic() < render_deadline:
                    show_more = page.get_by_role(
                        "button", name=re.compile(r"Mostrar más vuelos", re.IGNORECASE)
                    )
                    if not show_more.count():
                        break
                    show_more.last.click()
                    page.wait_for_timeout(1000)
                if fare_cards.count() <= fare_index:
                    result["error"] = (
                        f"e_n_fare_card_not_rendered:index={fare_index}:"
                        f"cards={fare_cards.count()}"
                    )
                    raise RuntimeError("E/N fare card was not rendered")
                fare_cards.nth(fare_index).click()
                page.wait_for_timeout(2000)
                page.get_by_role("button", name="Comprar", exact=True).click()
                page.get_by_role("button", name="Aceptar", exact=True).last.click()
                page.wait_for_url(re.compile(r"/checkout/passengers"))
                first_name = page.locator("input[name='passengers.0.passenger_firstName']")
                try:
                    first_name.wait_for(state="visible", timeout=30_000)
                except Exception:
                    if "/checkout-error" in page.url:
                        result.update(status="security_blocked", error="checkout_security_validation_failed")
                        raise RuntimeError("checkout security validation failed")
                    result["checkout_refreshed"] = True
                    page.reload(wait_until="domcontentloaded")
                    try:
                        first_name.wait_for(state="visible", timeout=15_000)
                    except Exception:
                        result["error"] = "checkout_form_not_loaded_after_refresh"
                        raise RuntimeError("checkout form not loaded after refresh")

                first_name.fill("LOL")
                page.locator("input[name='passengers.0.passenger_lastName']").fill("LOL")
                select_react_option(page, 0, "1")
                select_react_option(page, 1, "Febrero")
                select_react_option(page, 2, "2003")
                page.get_by_text("Femenino", exact=True).click()
                select_react_option(page, 3, "DNI")
                page.locator("input[name='passengers.0.passenger_documentNumber']").fill("999999999")
                select_react_option(page, 4, "Afganistán")
                page.wait_for_timeout(500)
                select_react_option(page, 5, "3")
                select_react_option(page, 6, "Enero")
                select_react_option(page, 7, "2032")
                select_react_option(page, 8, "Afganistán")

                page.locator("input[name='contactInformation_email']").fill("l@l.com")
                page.locator("input[name='contactInformation_confirmationEmail']").fill("l@l.com")
                page.locator("input[name='phone_type']").first.check(force=True)
                area_code = page.locator("input[name='contactInformation_areaCode']")
                phone_country = area_code.locator(
                    "xpath=preceding::input[starts-with(@id, 'react-select-')][1]"
                )
                select_react_control(page, phone_country, "Afganistán")
                area_code.fill("32")
                page.locator("input[name='contactInformation_phoneNumber']").fill("99999999")
                page.locator("input[type='checkbox']").nth(2).check()

                page.get_by_role("button", name="Seleccionar", exact=True).click()
                page.wait_for_timeout(5000)
                if result["passengers_status"] is None and "/checkout/passengers" in page.url:
                    body_lines = page.locator("body").inner_text().splitlines()
                    keywords = ("oblig", "requer", "válid", "seleccion", "complet", "acept")
                    result["validation_messages"] = [
                        line.strip() for line in body_lines
                        if line.strip() and any(word in line.lower() for word in keywords)
                    ][-20:]
                    result["selected_values"] = page.locator("input[type='hidden']").evaluate_all(
                        "els => Object.fromEntries(els.filter(e => e.name).map(e => [e.name, e.value]))"
                    )
                    result["error"] = "passenger_form_validation_failed"
                deadline = time.monotonic() + args.timeout_seconds
                while result["error"] is None and time.monotonic() < deadline and ancillary_payload is None:
                    if "/checkout-error" in page.url:
                        result.update(status="security_blocked", error="checkout_security_validation_failed")
                        break
                    page.wait_for_timeout(500)
                if ancillary_payload is not None:
                    result.update(status="ok", ancillaries=parse_ancillaries(ancillary_payload))
                elif result["status"] == "error" and result["error"] is None:
                    result["error"] = "ancillaries_response_not_received"
        except Exception as exc:
            if result["error"] is None:
                result["error"] = f"{type(exc).__name__}: {exc}"
            if "/checkout-error" in page.url:
                result["status"] = "security_blocked"
        finally:
            if offers_payload is not None and selected_offer_id is not None:
                result.update(selected_offer_details(offers_payload, selected_offer_id))
            result["final_url"] = page.url
            result["page_title"] = page.title()
            try:
                result["page_text_excerpt"] = page.locator("body").inner_text()[-1000:]
            except Exception:
                pass
            context.close()
            browser.close()

    result["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"output={output}")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
