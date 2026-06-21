# tools/

Operator scripts run inside the container
(`docker exec solar-payoff python3 /tmp/<script>.py`). These will move into the
dashboard UI over time (W-419); for now they're command-line helpers.

## fetch_pvwatts.py

Fetches expected annual production from PVWatts and stores it (settings key
`pv_expected_annual_kwh`) so the dashboard can show the **Performance** metric
(actual vs. expected). Edit the lat/lon/tilt/azimuth/capacity constants at the top
for your array, then run it.

Note: NREL was renamed (National Laboratory of the Rockies); `developer.nrel.gov`
was retired 2026-05-29 — the script uses `developer.nlr.gov`. Get a free key at
developer.nlr.gov; the script uses the rate-limited `DEMO_KEY` by default.

## calibrate_onpeak.py

For time-of-use rates: samples ~1 day per 5 over the last year of Enphase 15-minute
production, buckets each interval against the on-peak window, and stores the on-peak
production fraction per calendar month (settings `onpeak_frac_by_month`). The payoff
calc uses this to value production at the right TOU rate. The on-peak window is set
in the script (12pm–8pm Mon–Fri). Throttle ≥7s/call — Enphase's Watt plan caps at
10 hits/min.

## Bespoke integrations

The Eversource Mail.app statement-PDF pipeline moved to
`examples/eversource-statements/` — it's custom and not part of the default path.
Use Green Button upload in the dashboard for utility data.
