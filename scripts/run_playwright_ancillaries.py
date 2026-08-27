"""Run one visible-browser search through ancillary price retrieval."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import time

from playwright.sync_api import Page, sync_playwright

from aerolineas_argentinas.parsers import parse_ancillaries
from aerolineas_argentinas.routes import offers_url


def select_react_option(page: Page, index: int, value: str) -> None:
    controls = page.locator("input[id^='react-select-']")
    control = controls.last if index == -1 else controls.nth(index)
    control.click(force=True)
    control.fill(value)
    page.wait_for_timeout(200)
    page.locator("[role='option']").filter(
        has_text=re.compile(rf"^{re.escape(value)}(?:\s|$)", re.IGNORECASE)
    ).first.click()


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
        "error": None,
        "final_url": None,
        "validation_messages": [],
        "selected_values": {},
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    ancillary_payload = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(locale="es-AR", viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.set_default_timeout(args.timeout_seconds * 1000)

        def capture_response(response) -> None:
            nonlocal ancillary_payload
            if "/v2/checkout/passengers" in response.url and response.request.method == "POST":
                result["passengers_status"] = response.status
            if "/v2/checkout/ancillaries" in response.url:
                result["ancillaries_status"] = response.status
                if response.ok:
                    try:
                        ancillary_payload = response.json()
                    except Exception:
                        pass

        page.on("response", capture_response)
        try:
            page.goto(
                offers_url(args.origin, args.destination, args.date, flex=False),
                wait_until="domcontentloaded",
            )
            if page.title() == "403 Forbidden":
                result.update(status="security_blocked", error="initial_request_403")
            else:
                cookie_button = page.get_by_role("button", name="Aceptar solo las esenciales")
                if cookie_button.count():
                    cookie_button.last.click(force=True)
                    page.wait_for_timeout(500)

                page.locator("button[class*='FareContainer']").first.click()
                page.wait_for_timeout(2000)
                page.get_by_role("button", name="Comprar", exact=True).click()
                page.get_by_role("button", name="Aceptar", exact=True).last.click()
                page.wait_for_url(re.compile(r"/checkout/passengers"))
                page.wait_for_timeout(2000)
                if "/checkout-error" in page.url:
                    result.update(status="security_blocked", error="checkout_security_validation_failed")
                    raise RuntimeError("checkout security validation failed")

                page.locator("input[name='passengers.0.passenger_firstName']").fill("LOL")
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
                select_react_option(page, -1, "Afganistán")
                page.locator("input[name='contactInformation_areaCode']").fill("32")
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
            result["error"] = f"{type(exc).__name__}: {exc}"
            if "/checkout-error" in page.url:
                result["status"] = "security_blocked"
        finally:
            result["final_url"] = page.url
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
