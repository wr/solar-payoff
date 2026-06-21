# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-tenant, self-hosted dashboard that tracks how far along a home solar
install is toward paying for itself. It pulls daily production/consumption from
the Enphase Enlighten API, values it against the user's configured electricity
rate (flat or time-of-use), and computes avoided-cost savings + a break-even
projection. Optional: Green Button upload for real bill amounts, PVWatts for a
performance metric. Runs in Docker, one SQLite file, vanilla-JS SPA.

Being open-sourced for self-hosting (W-419). Keep it generic and config-driven —
nothing system-specific in code; personal data lives in the gitignored DB/.env.
Eversource statement parsing is a custom example under `examples/`, not the
default path; Green Button is the portable utility import.

## Run / build

```bash
docker compose up -d --build          # build + run, dashboard on http://localhost:8088
docker compose logs -f solar-payoff   # tail logs
docker compose down                   # stop
```

Local (no Docker) for quick iteration:

```bash
pip install -r requirements.txt
DB_PATH=./data/solar.db uvicorn app.main:app --reload --port 8000
```

There is no test suite, linter, or build step. The frontend is static files
served directly — no bundler, no npm. `static/chart.umd.min.js` is vendored
Chart.js.

Enphase app credentials go in a host `.env` (see `.env.example`); they're passed
through `docker-compose.yml` as env vars and take precedence over anything stored
in the DB (`config.enphase_creds()`). The SQLite DB lives in the `/data` volume
(`./data` on the host) and survives rebuilds.

## Architecture

FastAPI app (`app/main.py`) with a `lifespan` hook that runs `db.init_db()`,
`config.ensure_defaults()`, and starts the background scheduler. Module map:

- `db.py` — stdlib `sqlite3`, no ORM. Three things live here: a `settings`
  key/value table (credentials, tokens, financials, calibration JSON all stuffed
  in as strings), `daily_energy` (Enphase, Wh), and `utility_daily` (per
  billing-cycle grid data). Schema changes are append-only `ALTER TABLE` entries
  in `_MIGRATIONS` that swallow "column exists" errors — add new columns there,
  never edit `SCHEMA` destructively.
- `config.py` — reads/writes the financial settings (install cost, rates,
  warranty terms) and resolves Enphase creds (env wins over DB). `FINANCIAL_DEFAULTS`
  is the canonical list of user-editable settings exposed in the UI.
- `enphase.py` — Enlighten API v4 client. OAuth2 with auto-refresh (`_access_token()`
  refreshes 5 min early; `_api_get` retries once on 401). `sync()` pulls full
  lifetime production + consumption history and upserts daily rows. Default
  redirect is Enphase's on-screen code page (manual paste); set
  `ENPHASE_REDIRECT_URI` to enable the one-click callback.
- `greenbutton.py` — parses Eversource "Green Button" exports (ESPI Atom XML, CSV,
  or ZIP of either) into daily import kWh + cost. This is the *self-serve* utility
  import path via the UI upload.
- `payoff.py` — the heart of the app. Read its module docstring before touching it.
- `scheduler.py` — APScheduler cron job, daily 06:15, calls `enphase.sync()` wrapped
  to record `last_sync` / `last_sync_error` in settings.
- `static/` — `index.html` + `app.js` + `styles.css`. `app.js` fetches
  `/api/status` and `/api/payoff` and renders everything client-side with Chart.js.

### The payoff model (payoff.py)

Savings = avoided cost, computed per billing cycle as TOU-weighted production
value: `production_on-peak × rate_on + production_off-peak × rate_off`. Because
this is the *difference* between the no-solar and actual variable bill, the fixed
customer charge cancels and never affects savings.

Each cycle gets an effective $/kWh (`eff = f_on·rate_on + (1−f_on)·rate_off`);
that rate is applied to each day's production so the daily series sums back to the
per-cycle avoided cost. When a cycle is missing a component (rate or on-peak
fraction), it falls back seasonally (by calendar month), then to an overall
average, then to the flat `electricity_rate` setting.

The on-peak production fraction comes from `onpeak_frac_by_month` in settings
(measured from 15-min interval data — see calibration tool below) when present;
otherwise from the meter's export-timing proxy stored per cycle. Real net bills
from Eversource statements override the model's estimated cost in the monthly
breakdown (`actual_cost_is_real`).

## Out-of-band data tools (`tools/`)

These run on the **Mac host** or **inside the container**, not as part of the web
app. They backfill data the live sync can't get. Read `tools/README.md` for the
full pipeline; the short version:

- **Eversource statement backfill** (custom, moved to
  `examples/eversource-statements/`) — the original author's real net bills came
  from statement *emails* (PDF attachments) via Mail.app, not the API.
  `dump_all.applescript` → `batch_parse.py` → load via `db.upsert_utility_daily`
  inside the container. Mac + Eversource-specific; not part of the default path.
  Most forks use Green Button instead.
- `calibrate_onpeak.py` — samples ~1 day per 5 over the last year of Enphase
  15-min production, buckets each interval against the 12pm–8pm Mon–Fri ET on-peak
  window, stores `onpeak_frac_by_month`. Run inside the container. **Throttle
  ≥7s/call** — the Enphase Watt plan caps at 10 hits/min.
- `fetch_pvwatts.py` — fetches expected annual production from PVWatts and stores
  `pv_expected_annual_kwh` (drives the Performance metric). Site/array params are
  hardcoded for this specific install.

## Gotchas

- All dates are `YYYY-MM-DD` strings; timezone is fixed to `America/New_York` via
  the container `TZ`, which matters for Green Button interval-to-day bucketing and
  on-peak windowing.
- Settings values are always stored as strings; `config.py` and `payoff.py` parse
  them defensively (lots of `try/except (ValueError, TypeError)`). Keep that
  pattern — a blank or garbage setting must never crash the payoff endpoint.
- Enphase consumption monitoring may be off; `sync()` and the payoff math both
  degrade to production-only rather than erroring.
- `upsert_*` uses `COALESCE(excluded.col, table.col)` so a partial sync (e.g.
  production-only) never wipes existing columns. Use `replace_utility_daily` only
  for the full statement rebuild.
