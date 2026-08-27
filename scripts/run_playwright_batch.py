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

from aerolineas_argentinas.routes import parse_route


ROUTES = "BRCBUE BRCMDZ BUECOR BUECPC BUECRD BUEFTE BUEIGR BUEMDZ BUENQN BUEJUJ BUESLA BUETUC BUEUSH MDZSLA NQNSLA BUERES BUEPSS BUESDE BUEUAQ BUEREL".split()


def flatten_result(result: dict) -> dict:
    row = {key: value for key, value in result.items() if key != "ancillaries"}
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
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--routes", nargs="*", default=ROUTES)
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--pause-seconds", type=int, default=3)
    parser.add_argument(
        "--output",
        default=str(Path.home() / "Downloads" / "aerolineas_playwright_batch.parquet"),
    )
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result_dir = output.with_suffix("")
    result_dir.mkdir(parents=True, exist_ok=True)
    runner = Path(__file__).with_name("run_playwright_ancillaries.py")
    results = []
    batch_started = time.perf_counter()

    for index, route in enumerate(args.routes, start=1):
        origin, destination = parse_route(route)
        route_output = result_dir / f"{route.upper()}.json"
        print(f"[{index}/{len(args.routes)}] {origin}-{destination}", flush=True)
        command = [
            sys.executable,
            str(runner),
            "--origin", origin,
            "--destination", destination,
            "--date", args.date.isoformat(),
            "--timeout-seconds", str(args.timeout_seconds),
            "--output", str(route_output),
        ]
        completed = subprocess.run(command, env=os.environ.copy(), check=False)
        if route_output.exists():
            result = json.loads(route_output.read_text(encoding="utf-8"))
        else:
            result = {
                "route": route.upper(),
                "date": args.date.isoformat(),
                "status": "runner_error",
                "error": f"child_exit_code_{completed.returncode}",
                "elapsed_seconds": None,
            }
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
        "date": args.date.isoformat(),
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
