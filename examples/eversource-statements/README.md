# Eversource statement backfill (custom integration — not required)

This is the bespoke pipeline the original author used to get exact, time-of-use,
net-metered bill data for an Eversource (Connecticut) account by parsing the
statement PDFs out of a local **Mail.app** inbox. It is Mac-only and
Eversource-specific. Most people should ignore it and use **Green Button upload**
in the dashboard instead.

It's kept here as a reference for anyone who wants to do high-accuracy backfill
from their own utility's statement PDFs.

## What it does

1. `dump_all.applescript` — pulls every Eversource "Statement" email's raw source
   (PDF attachments included as MIME) from Mail.app via AppleScript:
   `osascript dump_all.applescript > /tmp/stmt_all.eml`
2. `batch_parse.py` + `parse_stmt.py` — decode the PDFs, run `pdftotext` (needs
   `brew install poppler`), and parse each statement into: billing period, gross
   purchase kWh (on/off-peak), solar export kWh (on/off-peak), net bill, and the
   per-peak marginal $/kWh. Handles several attachment layouts and rate-table
   formats:
   `python3 batch_parse.py /tmp/stmt_all.eml /tmp/parsed.jsonl`
3. Map each parsed row to `{date: period_to, import_kwh, cost: net_bill,
   export_kwh, rate_on, rate_off, onpeak_frac, period_from, fixed_charge}` and
   load it via `db.upsert_utility_daily` inside the container.

When statement rows carry `rate_on`/`rate_off`, the payoff calc uses them directly
(per-cycle TOU rates). Without them it falls back to the rate schedule you
configure in the dashboard.

## Why it's not in the default path

Every utility formats statements differently, and most don't email PDFs at all.
Green Button (the US standard export) is the portable way to get real usage/cost,
so that's what the app supports out of the box.
