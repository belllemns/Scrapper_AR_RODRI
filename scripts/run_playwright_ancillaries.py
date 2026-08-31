"""Run one visible-browser search through ancillary price retrieval."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse

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


def fill_text(locator, value: str) -> None:
    locator.click()
    locator.press_sequentially(value, delay=75)


def nearest_react_control_before(page: Page, locator):
    target_box = locator.bounding_box()
    if target_box is None:
        raise RuntimeError("target input is not visible")
    controls = page.locator("input[id^='react-select-']:visible")
    nearest = None
    nearest_distance = float("inf")
    for index in range(controls.count()):
        control = controls.nth(index)
        box = control.bounding_box()
        if box is None or box["y"] >= target_box["y"]:
            continue
        distance = target_box["y"] - box["y"]
        if distance < nearest_distance:
            nearest = control
            nearest_distance = distance
    if nearest is None:
        raise RuntimeError("phone country control was not found")
    return nearest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="BRC")
    parser.add_argument("--destination", default="BUE")
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--output", default=str(Path.home() / "Downloads" / "aerolineas_playwright_ancillaries.json"))
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument(
        "--user-data-dir",
        default=str(Path.home() / "AppData" / "Local" / "aerolineas-playwright-profile"),
    )
    parser.add_argument("--cdp-url")
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
        "checkout_refreshes": 0,
        "checkout_api_events": [],
        "selected_shopping_id": None,
        "checkout_shopping_id": None,
        "fare_card_reclicked": False,
        "selection_response_status": None,
        "selection_response_excerpt": None,
        "network_errors": [],
        "page_errors": [],
        "validation_messages": [],
        "selected_values": {},
        "offers_refreshes": 0,
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    ancillary_payload = None
    offers_payload = None
    selected_offer_id = None

    with sync_playwright() as playwright:
        owns_context = args.cdp_url is None
        if args.cdp_url:
            browser = playwright.chromium.connect_over_cdp(args.cdp_url)
            context = browser.contexts[0]
            page = context.new_page()
        else:
            context = playwright.chromium.launch_persistent_context(
                args.user_data_dir,
                channel="chrome",
                headless=False,
                locale="es-AR",
                viewport={"width": 1440, "height": 900},
            )
            page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(args.timeout_seconds * 1000)
        cdp = context.new_cdp_session(page)
        cdp.send("Network.enable")

        def record_checkout_event(kind: str, method: str, url: str, status=None) -> None:
            path = urlparse(url).path
            tracked = (
                "/checkout/" in path
                or "/rules/checkout/" in path
                or "paymentOptions" in path
                or "languageBundles/es-AR_checkout" in path
            )
            if tracked:
                result["checkout_api_events"].append({
                    "kind": kind,
                    "method": method,
                    "path": path,
                    "status": status,
                })

        def capture_response(response) -> None:
            nonlocal ancillary_payload, offers_payload
            record_checkout_event(
                "response",
                response.request.method,
                response.url,
                response.status,
            )
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
            if "/v1/flights/offers" in response.url and response.request.method == "POST":
                result["selection_response_status"] = response.status
                try:
                    result["selection_response_excerpt"] = response.text()[-1000:]
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
                request_data = json.loads(request.post_data or "{}")
                result["selected_shopping_id"] = request_data.get("shoppingId")
                if selected:
                    selected_offer_id = str(selected[0])
            except (TypeError, ValueError):
                pass

        page.on("request", capture_request)
        page.on("response", capture_response)
        page.on(
            "requestfailed",
            lambda request: record_checkout_event(
                "requestfailed", request.method, request.url
            ),
        )
        page.on("pageerror", lambda error: result["page_errors"].append(str(error)))
        try:
            search_url = offers_url(args.origin, args.destination, args.date, flex=False)
            page.goto(search_url, wait_until="domcontentloaded")
            if page.title() == "403 Forbidden":
                result.update(status="security_blocked", error="initial_request_403")
            else:
                offers_deadline = time.monotonic() + args.timeout_seconds
                while offers_payload is None and time.monotonic() < offers_deadline:
                    page.wait_for_timeout(500)
                if offers_payload is None:
                    result["offers_refreshes"] = 1
                    cdp.send("Network.clearBrowserCache")
                    page.goto(search_url, wait_until="domcontentloaded")
                    offers_deadline = time.monotonic() + args.timeout_seconds
                    while offers_payload is None and time.monotonic() < offers_deadline:
                        page.wait_for_timeout(500)
                    if offers_payload is None:
                        result["error"] = "offers_response_not_received_after_refresh"
                        raise RuntimeError("offers response not received after refresh")
                group_info = select_offer_group(offers_payload)
                if group_info is None:
                    result["error"] = "no_e_n_offer_for_exact_date"
                    raise RuntimeError("no E/N offer for exact date")
                selected_group, group_index, offer_index = group_info
                selected_offer = selected_group["offers"][offer_index]

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
                fare_card = fare_cards.nth(fare_index)
                fare_card.scroll_into_view_if_needed()
                total = selected_offer.get("fare", {}).get("total")
                displayed_total = (
                    f"{round(float(total)):,}".replace(",", ".")
                    if isinstance(total, (int, float)) else None
                )
                price_label = (
                    fare_card.get_by_text(displayed_total, exact=True)
                    if displayed_total else fare_card
                )
                try:
                    with page.expect_response(
                        lambda response: "/v1/flights/offers" in response.url
                        and response.request.method == "POST",
                        timeout=15_000,
                    ):
                        price_label.click()
                except Exception:
                    result["fare_card_reclicked"] = True
                    fare_card.focus()
                    with page.expect_response(
                        lambda response: "/v1/flights/offers" in response.url
                        and response.request.method == "POST",
                        timeout=15_000,
                    ):
                        fare_card.press("Enter")
                buy_button = page.get_by_role("button", name="Comprar", exact=True)
                buy_button.wait_for(state="visible", timeout=15_000)
                buy_button.click()
                page.get_by_role("button", name="Aceptar", exact=True).last.click()
                page.wait_for_url(re.compile(r"/checkout/passengers"))
                checkout_url = page.url
                result["checkout_shopping_id"] = dict(
                    item.split("=", 1)
                    for item in urlparse(checkout_url).query.split("&")
                    if "=" in item
                ).get("shoppingId")
                if result["checkout_shopping_id"] != result["selected_shopping_id"]:
                    result["error"] = "checkout_shopping_id_mismatch"
                    raise RuntimeError("checkout shopping ID does not match selected offer")
                first_name = page.locator("input[name='passengers.0.passenger_firstName']")
                for load_attempt in range(4):
                    try:
                        first_name.wait_for(state="visible", timeout=25_000)
                        break
                    except Exception:
                        if "/checkout-error" in page.url:
                            result.update(
                                status="security_blocked",
                                error="checkout_security_validation_failed",
                            )
                            raise RuntimeError("checkout security validation failed")
                        if load_attempt == 3:
                            result["error"] = "checkout_form_not_loaded_after_3_refreshes"
                            raise RuntimeError("checkout form not loaded after 3 refreshes")
                        result["checkout_refreshed"] = True
                        result["checkout_refreshes"] += 1
                        cdp.send("Network.clearBrowserCache")
                        page.goto(checkout_url, wait_until="domcontentloaded")

                fill_text(first_name, "LOL")
                fill_text(page.locator("input[name='passengers.0.passenger_lastName']"), "LOL")
                select_react_option(page, 0, "1")
                select_react_option(page, 1, "Febrero")
                select_react_option(page, 2, "2003")
                page.get_by_text("Femenino", exact=True).click()
                select_react_option(page, 3, "DNI")
                fill_text(
                    page.locator("input[name='passengers.0.passenger_documentNumber']"),
                    "999999999",
                )
                select_react_option(page, 4, "Afganistán")
                page.wait_for_timeout(500)
                select_react_option(page, 5, "3")
                select_react_option(page, 6, "Enero")
                select_react_option(page, 7, "2032")
                select_react_option(page, 8, "Afganistán")

                fill_text(page.locator("input[name='contactInformation_email']"), "l@l.com")
                fill_text(
                    page.locator("input[name='contactInformation_confirmationEmail']"),
                    "l@l.com",
                )
                page.locator("input[name='phone_type']").first.check(force=True)
                area_code = page.locator("input[name='contactInformation_areaCode']")
                phone_country = nearest_react_control_before(page, area_code)
                select_react_control(page, phone_country, "Afganistán")
                fill_text(area_code, "32")
                fill_text(
                    page.locator("input[name='contactInformation_phoneNumber']"),
                    "99999999",
                )
                page.locator("input[type='checkbox']").nth(2).check()
                page.wait_for_timeout(2000)

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
            page.close()
            if owns_context:
                context.close()

    result["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"output={output}")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
