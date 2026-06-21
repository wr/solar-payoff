"""SQLite storage layer. Plain stdlib sqlite3 — no ORM, keep it simple."""
import sqlite3
import os
import json
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "/data/solar.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Daily energy from Enphase (Wh). production/consumption may be NULL if unavailable.
CREATE TABLE IF NOT EXISTS daily_energy (
    date            TEXT PRIMARY KEY,   -- YYYY-MM-DD
    production_wh   INTEGER,
    consumption_wh  INTEGER
);

-- Per-billing-cycle grid data from Eversource statements (or Green Button).
-- Keyed by the cycle end date. cost = the real net bill you paid.
CREATE TABLE IF NOT EXISTS utility_daily (
    date        TEXT PRIMARY KEY,       -- YYYY-MM-DD (billing cycle end)
    import_kwh  REAL,                   -- gross kWh purchased from grid
    cost        REAL,                   -- net $ actually billed
    export_kwh  REAL,                   -- solar kWh sold back
    rate        REAL,                   -- blended all-in $/kWh (fallback/display)
    period_from TEXT,                   -- billing cycle start (YYYY-MM-DD)
    rate_on     REAL,                   -- on-peak all-in $/kWh
    rate_off    REAL,                   -- off-peak all-in $/kWh
    onpeak_frac REAL,                   -- fraction of solar production in on-peak
    fixed_charge REAL                   -- fixed customer service charge ($/cycle)
);
"""

# columns added after v1; ALTER is a no-op-safe migration for existing DBs
_MIGRATIONS = [
    "ALTER TABLE utility_daily ADD COLUMN export_kwh REAL",
    "ALTER TABLE utility_daily ADD COLUMN rate REAL",
    "ALTER TABLE utility_daily ADD COLUMN period_from TEXT",
    "ALTER TABLE utility_daily ADD COLUMN rate_on REAL",
    "ALTER TABLE utility_daily ADD COLUMN rate_off REAL",
    "ALTER TABLE utility_daily ADD COLUMN onpeak_frac REAL",
    "ALTER TABLE utility_daily ADD COLUMN fixed_charge REAL",
]


@contextmanager
def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA)
        for stmt in _MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists


# ---- settings (key/value store) -------------------------------------------

def get_setting(key, default=None):
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    return row["value"]


def set_setting(key, value):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, "" if value is None else str(value)),
        )


def get_all_settings():
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def set_settings(d):
    with get_db() as conn:
        for k, v in d.items():
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, "" if v is None else str(v)),
            )


# ---- daily energy ---------------------------------------------------------

def upsert_daily_energy(rows):
    """rows: iterable of (date, production_wh, consumption_wh). None values are
    coalesced so a production-only sync doesn't wipe a stored consumption value."""
    with get_db() as conn:
        conn.executemany(
            """
            INSERT INTO daily_energy(date, production_wh, consumption_wh)
            VALUES(:date, :prod, :cons)
            ON CONFLICT(date) DO UPDATE SET
                production_wh  = COALESCE(excluded.production_wh,  daily_energy.production_wh),
                consumption_wh = COALESCE(excluded.consumption_wh, daily_energy.consumption_wh)
            """,
            [{"date": d, "prod": p, "cons": c} for (d, p, c) in rows],
        )


def get_daily_energy():
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT date, production_wh, consumption_wh FROM daily_energy ORDER BY date"
        ).fetchall()]


# ---- utility (green button) ----------------------------------------------

_UCOLS = ("import_kwh", "cost", "export_kwh", "rate", "period_from",
          "rate_on", "rate_off", "onpeak_frac", "fixed_charge")


def upsert_utility_daily(rows):
    """rows: iterable of dicts with date + any of the utility columns."""
    norm = [{"date": r["date"], **{c: r.get(c) for c in _UCOLS}} for r in rows]
    sets = ", ".join(f"{c} = COALESCE(excluded.{c}, utility_daily.{c})" for c in _UCOLS)
    cols = ", ".join(("date",) + _UCOLS)
    vals = ", ".join(f":{c}" for c in ("date",) + _UCOLS)
    with get_db() as conn:
        conn.executemany(
            f"INSERT INTO utility_daily({cols}) VALUES({vals}) "
            f"ON CONFLICT(date) DO UPDATE SET {sets}", norm)


def replace_utility_daily(rows):
    """Wipe and replace all utility rows (used for the statement rebuild)."""
    with get_db() as conn:
        conn.execute("DELETE FROM utility_daily")
    upsert_utility_daily(rows)


def get_utility_daily():
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT date, import_kwh, cost, export_kwh, rate, period_from, "
            "rate_on, rate_off, onpeak_frac, fixed_charge "
            "FROM utility_daily ORDER BY date"
        ).fetchall()]
