"""Run ancillary extraction sequentially for a batch of routes."""
from __future__ import annotations

import argparse
import atexit
from datetime import date
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

import pyarrow as pa
import pyarrow.parquet as pq

from aerolineas_argentinas.routes import add_months, parse_route


ROUTES = "BRCBUE BRCMDZ BUECOR BUECPC BUECRD BUEFTE BUEIGR BUEMDZ BUENQN BUEJUJ BUESLA BUETUC BUEUSH MDZSLA NQNSLA BUERES BUEPSS BUESDE BUEUAQ BUEREL".split()


def launch_warm_chrome(profile_dir: Path) -> tuple[subprocess.Popen, str]:
    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    chrome = next((path for path in candidates if path.exists()), None)
    if chrome is None:
        raise RuntimeError("Google Chrome executable was not found")

    profile_dir.parent.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    cdp_url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            str(chrome),
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={profile_dir}",
            "--lang=es-AR",
            "--window-size=1440,900",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{cdp_url}/json/version", timeout=1) as response:
                if response.status == 200:
                    return process, cdp_url
        except Exception:
            if process.poll() is not None:
                break
            time.sleep(0.25)
    process.terminate()
    raise RuntimeError("Warm Chrome did not expose its CDP endpoint")


def stop_warm_chrome(process: subprocess.Popen, cdp_url: str) -> None:
    if process.poll() is not None:
        return
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            playwright.chromium.connect_over_cdp(cdp_url).close()
        process.wait(timeout=10)
    except Exception:
        process.terminate()


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


def write_batch_outputs(
    output: Path,
    results: list[dict],
    start_date: date,
    end_date: date,
    batch_started: float,
    requested_routes: int,
) -> dict:
    rows = [flatten_result(result) for result in results]
    if rows:
        pq.write_table(pa.Table.from_pylist(rows), output)
    summary = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "requested_routes": requested_routes,
        "attempted_routes": len(results),
        "ok": sum(result.get("status") == "ok" for result in results),
        "errors": sum(result.get("status") != "ok" for result in results),
        "elapsed_seconds": round(time.perf_counter() - batch_started, 2),
        "results": results,
    }
    output.with_suffix(".json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary


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
        "--resume",
        action="store_true",
        help="Skip routes that already have a successful result JSON.",
    )
    parser.add_argument(
        "--stop-on-security-block",
        action="store_true",
        help="Stop the batch after a security block instead of continuing.",
    )
    parser.add_argument(
        "--cold-browser",
        action="store_true",
        help="Launch a new Chrome for each child process instead of one warm Chrome.",
    )
    parser.add_argument(
        "--warm-profile-dir",
        default=str(Path.home() / "AppData" / "Local" / "aerolineas-playwright-warm-profile"),
    )
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
    cdp_url = None
    if not args.cold_browser:
        chrome_process, cdp_url = launch_warm_chrome(Path(args.warm_profile_dir))
        atexit.register(stop_warm_chrome, chrome_process, cdp_url)
        print(f"warm_chrome={cdp_url}", flush=True)

    for index, route in enumerate(args.routes, start=1):
        origin, destination = parse_route(route)
        route_dir = result_dir / route.upper()
        route_dir.mkdir(parents=True, exist_ok=True)
        route_output = route_dir / "result.json"
        if args.resume and route_output.exists():
            previous = json.loads(route_output.read_text(encoding="utf-8"))
            if (
                previous.get("status") == "ok"
                and previous.get("brand_id") == "EB"
                and previous.get("booking_class") in {"E", "N"}
                and previous.get("ancillaries_status") == 200
            ):
                results.append(previous)
                write_batch_outputs(
                    output, results, args.date, end_date, batch_started, len(args.routes)
                )
                print(f"[{index}/{len(args.routes)}] {route.upper()} status=ok resumed", flush=True)
                continue
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
        if cdp_url:
            calendar_command.extend(["--cdp-url", cdp_url])
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
                if cdp_url:
                    command.extend(["--cdp-url", cdp_url])
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
        route_output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        results.append(result)
        write_batch_outputs(
            output, results, args.date, end_date, batch_started, len(args.routes)
        )
        print(
            f"[{index}/{len(args.routes)}] {route.upper()} status={result.get('status')} "
            f"seconds={result.get('elapsed_seconds')}",
            flush=True,
        )
        if args.stop_on_security_block and result.get("status") == "security_blocked":
            print("security block detected; stopping with checkpoint saved", flush=True)
            break
        if index < len(args.routes) and args.pause_seconds:
            time.sleep(args.pause_seconds)

    summary = write_batch_outputs(
        output, results, args.date, end_date, batch_started, len(args.routes)
    )
    summary_path = output.with_suffix(".json")
    print(f"parquet={output}")
    print(f"summary={summary_path}")
    print(f"ok={summary['ok']} errors={summary['errors']} elapsed_seconds={summary['elapsed_seconds']}")
    return 0 if summary["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
