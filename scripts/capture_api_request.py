"""Capture the browser request used to search flight offers.

The capture is written locally so the request can be reproduced without
committing cookies, bearer tokens, or passenger data to the repository.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from aerolineas_argentinas.routes import offers_url


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url")
    parser.add_argument("--origin")
    parser.add_argument("--destination")
    parser.add_argument("--date")
    parser.add_argument("--flex", action="store_true")
    parser.add_argument("--with-ancillaries", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=8)
    parser.add_argument("--profile-dir", default="aerolineas-profile-api-capture")
    parser.add_argument(
        "--output",
        default=str(Path.home() / "Downloads" / "aerolineas_api_request_capture.json"),
    )
    args = parser.parse_args()
    if not args.url:
        if not all((args.origin, args.destination, args.date)):
            parser.error("use --url or --origin, --destination and --date")
        args.url = offers_url(
            args.origin,
            args.destination,
            date.fromisoformat(args.date),
            flex=args.flex,
        )

    options = Options()
    options.add_argument("--lang=es-AR")
    options.add_argument("--window-size=1440,900")
    options.add_argument("--disable-notifications")
    options.add_argument("--user-data-dir=" + str(Path(args.profile_dir).resolve()))
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = webdriver.Chrome(options=options)
    try:
        def is_target(url: str) -> bool:
            return any(path in url for path in (
                "/v1/flights/offers",
                "/v2/checkout/passengers",
                "/v2/checkout/ancillaries",
            ))

        driver.execute_cdp_cmd("Network.enable", {})
        driver.get(args.url)
        time.sleep(args.wait_seconds)
        if args.with_ancillaries:
            for _ in range(20):
                if driver.execute_script("""
                    [...document.querySelectorAll('button')]
                      .find(x => x.innerText.includes('Aceptar solo las esenciales'))?.click();
                    const card = [...document.querySelectorAll('button')]
                      .find(x => x.className.includes('FareContainer'));
                    if (card) { card.click(); return true; }
                    return false;
                """):
                    break
                time.sleep(1)
            for _ in range(20):
                if driver.execute_script("""
                    return Boolean(document.querySelector(
                      'input[name*=firstName i], input[id*=firstName i]'));
                """):
                    break
                time.sleep(1)
            driver.execute_script("""
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
                [...document.querySelectorAll('button')]
                  .find(x => /^(Continuar|Siguiente)$/i.test(x.innerText.trim()))?.click();
            """)
            time.sleep(args.wait_seconds)
        requests = []
        responses = []
        for entry in driver.get_log("performance"):
            try:
                message = json.loads(entry["message"])["message"]
            except (KeyError, TypeError, ValueError):
                continue
            params = message.get("params", {})
            if message.get("method") == "Network.requestWillBeSent":
                request = params.get("request", {})
                if is_target(request.get("url", "")):
                    requests.append({
                        "requestId": params.get("requestId"),
                        "method": request.get("method"),
                        "url": request.get("url"),
                        "headers": request.get("headers", {}),
                        "postData": request.get("postData"),
                    })
            elif message.get("method") == "Network.responseReceived":
                response = params.get("response", {})
                if is_target(response.get("url", "")):
                    responses.append({
                        "requestId": params.get("requestId"),
                        "status": response.get("status"),
                        "url": response.get("url"),
                    })
    finally:
        driver.quit()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"requests": requests, "responses": responses}, indent=2),
        encoding="utf-8",
    )
    print(f"requests={len(requests)} responses={len(responses)}")
    print(f"capture={output}")
    return 0 if requests else 1


if __name__ == "__main__":
    raise SystemExit(main())
