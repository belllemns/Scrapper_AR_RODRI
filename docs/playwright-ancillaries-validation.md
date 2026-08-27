# Playwright ancillary extraction validated

The visible-browser runner completed the passenger and ancillary flow without
entering payment details or confirming a purchase.

## Validated Run

| Field | Result |
|---|---|
| Route | BRC-BUE |
| Travel date | 2026-09-30 |
| Runtime | 27.87 seconds |
| Passenger request | HTTP 200 |
| Ancillary request | HTTP 200 |
| Final step | `/checkout/ancillaries` |

## Captured Prices

| Product | Price (ARS) |
|---|---:|
| Special/oversized baggage | 77,440 |
| First checked bag up to 15 kg | 52,030 |
| Additional checked bag up to 15 kg | 60,500 |
| Carry-on baggage | 54,450 |

## Verification

```powershell
$env:PYTHONPATH = "src"
python scripts/run_playwright_ancillaries.py --origin BRC --destination BUE --date 2026-09-30
```

Expected outcome: `status=ok`, passenger and ancillary responses are HTTP 200,
and all four ancillary price fields are populated.
