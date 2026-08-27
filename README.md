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

For generated interaction code only:

```powershell
python -m playwright codegen --target=python --output=flow_generated.py https://www.aerolineas.com.ar/
```

## Tests

```powershell
$env:PYTHONPATH = "src"
pytest
```
