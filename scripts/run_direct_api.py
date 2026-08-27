"""Smoke test for the direct Aerolineas Argentinas offers API."""
from __future__ import annotations

import argparse
from datetime import date
import json
import os

from aerolineas_argentinas.api import fetch_offers
from aerolineas_argentinas.parsers import parse_offers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="BRC")
    parser.add_argument("--destination", default="BUE")
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    args = parser.parse_args()

    token = os.environ.get("AEROLINEAS_ACCESS_TOKEN")
    if not token:
        parser.error("AEROLINEAS_ACCESS_TOKEN no está definido")

    payload = fetch_offers(args.origin, args.destination, args.date, token)
    offers = parse_offers(payload, "E") or parse_offers(payload, "N")
    print(json.dumps({
        "origin": args.origin.upper(),
        "destination": args.destination.upper(),
        "date": args.date.isoformat(),
        "status": "ok" if offers else "not_found",
        "offers": offers,
    }, indent=2))
    return 0 if offers else 1


if __name__ == "__main__":
    raise SystemExit(main())
