import importlib.util
from pathlib import Path

import pyarrow as pa


spec = importlib.util.spec_from_file_location(
    "run_playwright_batch",
    Path(__file__).parents[1] / "scripts" / "run_playwright_batch.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_flatten_serializes_empty_checkout_bootstrap_status():
    row = module.flatten_result({
        "checkout_bootstrap_status": {},
        "checkout_bootstrap_attempts": [],
    })

    assert row["checkout_bootstrap_status"] == "{}"
    assert row["checkout_bootstrap_attempts"] == "[]"
    assert pa.Table.from_pylist([row]).num_rows == 1
