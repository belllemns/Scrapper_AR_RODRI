"""Chrome response capture."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options


def launch_driver(profile_dir: str) -> webdriver.Chrome:
    options = Options()
    options.add_argument("--lang=es-AR")
    options.add_argument("--window-size=1440,900")
    options.add_argument("--disable-notifications")
    options.add_argument("--user-data-dir=" + str(Path(profile_dir).resolve()))
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    return webdriver.Chrome(options=options)


def capture_api_responses(driver: Any) -> list[dict[str, Any]]:
    captured = []
    for entry in driver.get_log("performance"):
        try:
            message = json.loads(entry["message"])["message"]
        except (KeyError, TypeError, ValueError):
            continue
        if message.get("method") != "Network.responseReceived":
            continue
        response = message["params"].get("response", {})
        url = response.get("url", "")
        if ("api.aerolineas.com.ar/v1/flights/offers" not in url
                and "api.aerolineas.com.ar/v2/checkout/ancillaries" not in url):
            continue
        body = None
        try:
            raw = driver.execute_cdp_cmd(
                "Network.getResponseBody", {"requestId": message["params"]["requestId"]}
            ).get("body", "")
            body = json.loads(raw) if raw else None
        except Exception:
            pass
        captured.append({"url": url, "status": response.get("status"), "body": body})
    return captured
