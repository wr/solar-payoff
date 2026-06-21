"""Config helpers. App-level Enphase credentials come from env (preferred) or the
settings table. User-tunable financials live in the settings table, editable in UI."""
import os
from . import db

# Keys that are user-facing financial settings (exposed/editable in the dashboard).
FINANCIAL_DEFAULTS = {
    "install_cost_gross": "0",     # total sticker price
    "incentives": "0",             # tax credits + rebates (subtracted from gross)
    "switchon_date": "",           # YYYY-MM-DD the system went live (PTO)
    "electricity_rate": "0.30",    # $/kWh all-in retail (supply + delivery)
    "export_rate": "",             # $/kWh for exported solar; blank => same as retail (net metering)
    "payoff_metric": "avoided_cost",  # avoided_cost | retail_value
    "panel_warranty_yr": "25",     # warranty terms (years from switch-on)
    "inverter_warranty_yr": "25",
    "workmanship_warranty_yr": "25",
    # rate schedule used when a billing cycle has no statement-parsed rate
    "rate_mode": "flat",           # flat | tou
    "tou_on_rate": "",             # $/kWh on-peak (tou mode)
    "tou_off_rate": "",            # $/kWh off-peak (tou mode)
    "onpeak_start": "12",          # on-peak window start hour (0-23, local)
    "onpeak_end": "20",            # on-peak window end hour (exclusive)
    "onpeak_days": "weekdays",     # weekdays | all
    # location + array for the PVWatts performance metric
    "pv_lat": "",
    "pv_lon": "",
    "pv_tilt": "",
    "pv_azimuth": "",
    "nlr_api_key": "",             # developer.nlr.gov key (DEMO_KEY if blank)
}


def enphase_creds():
    """Return (api_key, client_id, client_secret). Env wins over DB."""
    return (
        os.environ.get("ENPHASE_API_KEY") or db.get_setting("enphase_api_key", ""),
        os.environ.get("ENPHASE_CLIENT_ID") or db.get_setting("enphase_client_id", ""),
        os.environ.get("ENPHASE_CLIENT_SECRET") or db.get_setting("enphase_client_secret", ""),
    )


def public_base_url():
    return os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")


def get_financials():
    s = db.get_all_settings()
    out = {}
    for k, default in FINANCIAL_DEFAULTS.items():
        out[k] = s.get(k, default) or default
    return out


def net_install_cost():
    f = get_financials()
    try:
        return float(f["install_cost_gross"]) - float(f["incentives"])
    except (ValueError, TypeError):
        return 0.0


def retail_rate():
    try:
        return float(get_financials()["electricity_rate"])
    except (ValueError, TypeError):
        return 0.0


def export_rate():
    f = get_financials()
    val = f.get("export_rate", "")
    if val in (None, ""):
        return retail_rate()
    try:
        return float(val)
    except (ValueError, TypeError):
        return retail_rate()


def ensure_defaults():
    s = db.get_all_settings()
    missing = {k: v for k, v in FINANCIAL_DEFAULTS.items() if k not in s}
    if missing:
        db.set_settings(missing)
