"""Record a manual checkout flow and its API traffic locally."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


TARGETS = ("/v1/flights/offers", "/v2/checkout/passengers", "/v2/checkout/ancillaries")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://www.aerolineas.com.ar/")
    parser.add_argument("--output-dir", default=str(Path.home() / "Downloads" / "aerolineas-playwright"))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    traffic: list[dict] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(
            locale="es-AR",
            record_har_path=output_dir / "flow.har",
            record_har_content="embed",
        )
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()

        def record_request(request) -> None:
            if any(target in request.url for target in TARGETS):
                traffic.append({
                    "kind": "request",
                    "method": request.method,
                    "url": request.url,
                    "headers": request.headers,
                    "post_data": request.post_data,
                })

        def record_response(response) -> None:
            if any(target in response.url for target in TARGETS):
                body = None
                if "/v2/checkout/ancillaries" in response.url:
                    try:
                        body = response.json()
                    except Exception:
                        body = None
                traffic.append({
                    "kind": "response",
                    "status": response.status,
                    "url": response.url,
                    "body": body,
                })

        page.on("request", record_request)
        page.on("response", record_response)
        page.goto(args.url, wait_until="domcontentloaded")
        print("Completa manualmente la búsqueda y el pasajero con datos fake.")
        print("No confirmes pagos ni compras. Pulsa Enter aquí al terminar el flujo.")
        input()
        context.tracing.stop(path=output_dir / "flow.zip")
        context.close()
        browser.close()

    (output_dir / "network.json").write_text(
        json.dumps(traffic, indent=2), encoding="utf-8"
    )
    print(f"trace={output_dir / 'flow.zip'}")
    print(f"har={output_dir / 'flow.har'}")
    print(f"network={output_dir / 'network.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
