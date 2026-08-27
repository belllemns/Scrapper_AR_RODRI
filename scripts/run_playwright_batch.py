"""Run ancillary extraction sequentially for a batch of routes."""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pyarrow as pa
import pyarrow.parquet as pq

from aerolineas_argentinas.routes import add_months, parse_route


ROUTES = "BRCBUE BRCMDZ BUECOR BUECPC BUECRD BUEFTE BUEIGR BUEMDZ BUENQN BUEJUJ BUESLA BUETUC BUEUSH MDZSLA NQNSLA BUERES BUEPSS BUESDE BUEUAQ BUEREL".split()


def flatten_result(result: dict) -> dict:
    defaults = {
        "date": None,
        "status": None,
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
        "passengers_status": None,
        "ancillaries_status": None,
        "error": None,
    }
    row = defaults | {
        key: value for key, value in result.items() if key != "ancillaries"
    }
    row.update(result.get("ancillaries") or {
        "special_baggage_price": None,
        "checked_baggage_price": None,
        "checked_baggage_additional_price": None,
        "hand_baggage_price": None,
    })
    row["validation_messages"] = json.dumps(
        row.get("validation_messages", []), ensure_ascii=False
    )
    row["selected_values"] = json.dumps(
        row.get("selected_values", {}), ensure_ascii=False
    )
    row["attempt_history"] = json.dumps(
        row.get("attempt_history", []), ensure_ascii=False
    )
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--routes", nargs="*", default=ROUTES)
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--calendar-candidates", type=int, default=5)
    parser.add_argument("--attempts-per-date", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--pause-seconds", type=int, default=10)
    parser.add_argument(
        "--output",
        default=str(Path.home() / "Downloads" / "aerolineas_playwright_batch.parquet"),
    )
    args = parser.parse_args()
    end_date = args.end_date or add_months(args.date, 6)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result_dir = output.with_suffix("")
    result_dir.mkdir(parents=True, exist_ok=True)
    runner = Path(__file__).with_name("run_playwright_ancillaries.py")
    calendar_runner = Path(__file__).with_name("find_playwright_calendar_candidates.py")
    results = []
    batch_started = time.perf_counter()

    for index, route in enumerate(args.routes, start=1):
        origin, destination = parse_route(route)
        route_dir = result_dir / route.upper()
        route_dir.mkdir(parents=True, exist_ok=True)
        calendar_output = route_dir / "calendar.json"
        print(f"[{index}/{len(args.routes)}] {origin}-{destination}", flush=True)
        calendar_command = [
            sys.executable,
            str(calendar_runner),
            "--origin", origin,
            "--destination", destination,
            "--start-date", args.date.isoformat(),
            "--end-date", end_date.isoformat(),
            "--limit", str(args.calendar_candidates),
            "--timeout-seconds", str(args.timeout_seconds),
            "--output", str(calendar_output),
        ]
        subprocess.run(calendar_command, env=os.environ.copy(), check=False)
        calendar = (
            json.loads(calendar_output.read_text(encoding="utf-8"))
            if calendar_output.exists() else {}
        )
        candidates = calendar.get("candidates", [])
        attempt_history = []
        result = None
        stop_route = False
        for candidate in candidates:
            candidate_date = candidate["date"]
            for attempt in range(1, args.attempts_per_date + 1):
                attempt_output = route_dir / f"{candidate_date}_attempt_{attempt}.json"
                command = [
                    sys.executable,
                    str(runner),
                    "--origin", origin,
                    "--destination", destination,
                    "--date", candidate_date,
                    "--timeout-seconds", str(args.timeout_seconds),
                    "--output", str(attempt_output),
                ]
                completed = subprocess.run(command, env=os.environ.copy(), check=False)
                if attempt_output.exists():
                    current = json.loads(attempt_output.read_text(encoding="utf-8"))
                else:
                    current = {
                        "route": route.upper(),
                        "date": candidate_date,
                        "status": "runner_error",
                        "error": f"child_exit_code_{completed.returncode}",
                        "elapsed_seconds": None,
                    }
                attempt_history.append({
                    "date": candidate_date,
                    "calendar_booking_class": candidate.get("booking_class"),
                    "calendar_base_fare": candidate.get("base_fare"),
                    "attempt": attempt,
                    "status": current.get("status"),
                    "error": current.get("error"),
                })
                result = current
                if current.get("status") == "ok":
                    stop_route = True
                    break
                if current.get("status") == "security_blocked":
                    stop_route = True
                    break
                if args.pause_seconds:
                    time.sleep(args.pause_seconds)
            if stop_route:
                break

        if result is None:
            result = {
                "route": route.upper(),
                "date": None,
                "status": calendar.get("status", "calendar_error"),
                "error": calendar.get("error", "calendar_result_missing"),
                "elapsed_seconds": calendar.get("elapsed_seconds"),
            }
        result["calendar_start_date"] = args.date.isoformat()
        result["calendar_end_date"] = end_date.isoformat()
        result["calendar_candidates"] = len(candidates)
        result["attempt_history"] = attempt_history
        route_output = route_dir / "result.json"
        route_output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        results.append(result)
        print(
            f"[{index}/{len(args.routes)}] {route.upper()} status={result.get('status')} "
            f"seconds={result.get('elapsed_seconds')}",
            flush=True,
        )
        if index < len(args.routes) and args.pause_seconds:
            time.sleep(args.pause_seconds)

    rows = [flatten_result(result) for result in results]
    pq.write_table(pa.Table.from_pylist(rows), output)
    summary = {
        "start_date": args.date.isoformat(),
        "end_date": end_date.isoformat(),
        "routes": len(results),
        "ok": sum(result.get("status") == "ok" for result in results),
        "errors": sum(result.get("status") != "ok" for result in results),
        "elapsed_seconds": round(time.perf_counter() - batch_started, 2),
        "results": results,
    }
    summary_path = output.with_suffix(".json")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"parquet={output}")
    print(f"summary={summary_path}")
    print(f"ok={summary['ok']} errors={summary['errors']} elapsed_seconds={summary['elapsed_seconds']}")
    return 0 if summary["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
