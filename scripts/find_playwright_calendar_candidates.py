"""Find the cheapest E/N travel dates from the flexible-date calendar."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import time

from playwright.sync_api import sync_playwright

from aerolineas_argentinas.parsers import calendar_candidates
from aerolineas_argentinas.routes import add_months, offers_url


def month_starts(start: date, end: date) -> list[date]:
    current = start.replace(day=1)
    result = []
    while current <= end:
        result.append(current)
        current = add_months(current, 1)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    started = time.perf_counter()
    payloads = []
    status = "ok"
    error = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(locale="es-AR", viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.set_default_timeout(args.timeout_seconds * 1000)

        def capture_response(response) -> None:
            if "/v1/flights/offers" not in response.url or response.request.method != "GET":
                return
            if not response.ok:
                return
            try:
                payload = response.json()
                if payload.get("calendarOffers"):
                    payloads.append(payload)
            except Exception:
                pass

        page.on("response", capture_response)
        try:
            for anchor in month_starts(args.start_date, args.end_date):
                previous_count = len(payloads)
                page.goto(
                    offers_url(args.origin, args.destination, anchor, flex=True),
                    wait_until="domcontentloaded",
                )
                if page.title() == "403 Forbidden":
                    status, error = "security_blocked", "initial_request_403"
                    break
                deadline = time.monotonic() + args.timeout_seconds
                while len(payloads) == previous_count and time.monotonic() < deadline:
                    page.wait_for_timeout(500)
        except Exception as exc:
            status, error = "error", f"{type(exc).__name__}: {exc}"
        finally:
            context.close()
            browser.close()

    by_date = {}
    for payload in payloads:
        shopping_id = payload.get("searchMetadata", {}).get("shoppingId")
        for candidate in calendar_candidates(payload):
            if candidate.get("booking_class") not in {"E", "N"}:
                continue
            candidate_date = candidate.get("date")
            if not candidate_date or not (
                args.start_date.isoformat() <= candidate_date <= args.end_date.isoformat()
            ):
                continue
            candidate["shopping_id"] = shopping_id
            current = by_date.get(candidate_date)
            candidate_price = candidate.get("base_fare")
            current_price = current.get("base_fare") if current else None
            if current is None or (
                candidate_price is not None
                and (current_price is None or candidate_price < current_price)
            ):
                by_date[candidate_date] = candidate

    candidates = sorted(
        by_date.values(),
        key=lambda item: (
            item.get("base_fare") is None,
            item.get("base_fare") or 0,
            item.get("date"),
        ),
    )[:args.limit]
    if status == "ok" and not candidates:
        status, error = "not_found", "no_e_n_calendar_candidates"

    result = {
        "route": f"{args.origin.upper()}{args.destination.upper()}",
        "start_date": args.start_date.isoformat(),
        "end_date": args.end_date.isoformat(),
        "status": status,
        "error": error,
        "calendar_responses": len(payloads),
        "candidates": candidates,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"output={output}")
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
