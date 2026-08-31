# Aerolineas Argentinas scraper

## Playwright flow recording

Install Playwright and Chromium:

```powershell
python -m pip install -e ".[playwright]"
python -m playwright install chromium
```

Record the flow with a visible browser:

```powershell
$env:PYTHONPATH = "src"
python scripts/record_playwright_flow.py
```

Complete the search and passenger form with fake data, stop before payment,
and press Enter in the terminal. The local `Downloads/aerolineas-playwright/`
folder will contain a HAR, a trace ZIP, and filtered network requests for
offers, passengers, and ancillaries. These files contain session data and are
ignored by Git.

## Automatic ancillary run

Run one visible-browser search through passenger registration and ancillary
price retrieval:

```powershell
$env:PYTHONPATH = "src"
python scripts/run_playwright_ancillaries.py --origin BRC --destination BUE --date 2026-09-30
```

The script uses the configured fake passenger, stops on the ancillary page,
and writes a JSON result to `Downloads`. It never enters payment details or
confirms a purchase. A missing ancillary response is reported as an error,
not as unavailable baggage.

Run all configured routes sequentially and create a consolidated Parquet:

```powershell
$env:PYTHONPATH = "src"
python scripts/run_playwright_batch.py --date 2026-09-30
```

The batch pauses between routes, keeps one diagnostic JSON per route, and
continues when an individual route is blocked or fails validation. It searches
the next six calendar months by default, orders E/N dates by calendar fare,
prefers E over N on the exact date, and retries in fresh tabs. It checkpoints
the Parquet and summary after every route and continues after security blocks
unless `--stop-on-security-block` is set. Pass `--resume` to skip routes already
completed successfully.

By default the batch launches one warm Google Chrome instance and reuses it for
calendar and checkout requests, preserving the browser validation state while
opening a fresh tab per operation. Pass `--cold-browser` only for diagnostics.

For generated interaction code only:

```powershell
python -m playwright codegen --target=python --output=flow_generated.py https://www.aerolineas.com.ar/
```

## Tests

```powershell
$env:PYTHONPATH = "src"
pytest
```
