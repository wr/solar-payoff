"""Enphase Enlighten API v4 client: OAuth2 + daily production/consumption sync."""
import base64
import time
from datetime import datetime, timedelta, date

import httpx

from . import db, config

OAUTH_AUTHORIZE = "https://api.enphaseenergy.com/oauth/authorize"
OAUTH_TOKEN = "https://api.enphaseenergy.com/oauth/token"
API_BASE = "https://api.enphaseenergy.com/api/v4"
# Enphase shows the auth code on this page when no custom redirect is registered.
DEFAULT_REDIRECT = "https://api.enphaseenergy.com/oauth/redirect_uri"


class EnphaseError(Exception):
    pass


def _basic_auth_header(client_id, client_secret):
    raw = f"{client_id}:{client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def redirect_uri():
    """Default to Enphase's on-screen code page (manual paste) so setup works
    without registering anything. Set ENPHASE_REDIRECT_URI (and register it in
    the Enphase app) to enable the one-click callback flow instead."""
    import os
    return os.environ.get("ENPHASE_REDIRECT_URI") or DEFAULT_REDIRECT


def authorize_url():
    _, client_id, _ = config.enphase_creds()
    if not client_id:
        raise EnphaseError("Enphase Client ID not configured")
    return (
        f"{OAUTH_AUTHORIZE}?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={redirect_uri()}"
    )


def is_connected():
    return bool(db.get_setting("enphase_refresh_token"))


def _store_tokens(tok):
    db.set_settings({
        "enphase_access_token": tok["access_token"],
        "enphase_refresh_token": tok["refresh_token"],
        # access tokens last ~1 day; refresh ~1 week. Store absolute expiry.
        "enphase_token_expiry": str(int(time.time()) + int(tok.get("expires_in", 86400))),
    })


def exchange_code(code):
    _, client_id, client_secret = config.enphase_creds()
    if not (client_id and client_secret):
        raise EnphaseError("Enphase Client ID/Secret not configured")
    params = {
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri(),
        "code": code.strip(),
    }
    headers = {"Authorization": _basic_auth_header(client_id, client_secret)}
    r = httpx.post(OAUTH_TOKEN, params=params, headers=headers, timeout=30)
    if r.status_code != 200:
        raise EnphaseError(f"Token exchange failed ({r.status_code}): {r.text}")
    _store_tokens(r.json())


def _refresh():
    _, client_id, client_secret = config.enphase_creds()
    rt = db.get_setting("enphase_refresh_token")
    if not rt:
        raise EnphaseError("Not connected to Enphase")
    params = {"grant_type": "refresh_token", "refresh_token": rt}
    headers = {"Authorization": _basic_auth_header(client_id, client_secret)}
    r = httpx.post(OAUTH_TOKEN, params=params, headers=headers, timeout=30)
    if r.status_code != 200:
        raise EnphaseError(
            f"Token refresh failed ({r.status_code}): {r.text}. You may need to reconnect."
        )
    _store_tokens(r.json())


def _access_token():
    expiry = int(db.get_setting("enphase_token_expiry", "0") or "0")
    # refresh a little early to avoid edge expiry during a sync
    if time.time() > expiry - 300:
        _refresh()
    return db.get_setting("enphase_access_token")


def _api_get(path, params=None):
    api_key, _, _ = config.enphase_creds()
    token = _access_token()
    headers = {"Authorization": f"Bearer {token}", "key": api_key}
    r = httpx.get(f"{API_BASE}{path}", params=params or {}, headers=headers, timeout=60)
    if r.status_code == 401:
        # token might have just died; force one refresh + retry
        _refresh()
        headers["Authorization"] = f"Bearer {db.get_setting('enphase_access_token')}"
        r = httpx.get(f"{API_BASE}{path}", params=params or {}, headers=headers, timeout=60)
    if r.status_code != 200:
        raise EnphaseError(f"API {path} failed ({r.status_code}): {r.text}")
    return r.json()


def fetch_systems():
    return _api_get("/systems").get("systems", [])


def _resolve_system_id():
    sid = db.get_setting("enphase_system_id")
    if sid:
        return sid
    systems = fetch_systems()
    if not systems:
        raise EnphaseError("No systems found on this Enphase account")
    sid = str(systems[0]["system_id"])
    db.set_settings({
        "enphase_system_id": sid,
        "enphase_system_name": systems[0].get("name", ""),
    })
    return sid


def _lifetime_to_rows(payload, key):
    """Map an energy_lifetime/consumption_lifetime payload to {date: value_wh}."""
    start = payload.get("start_date")
    series = payload.get(key, [])
    if not start or not series:
        return {}
    start_d = datetime.strptime(start, "%Y-%m-%d").date()
    out = {}
    for i, val in enumerate(series):
        d = (start_d + timedelta(days=i)).isoformat()
        out[d] = val
    return out


def sync():
    """Pull full daily production + consumption history into daily_energy.
    Returns a summary dict."""
    sid = _resolve_system_id()

    prod_payload = _api_get(f"/systems/{sid}/energy_lifetime", {"production": "all"})
    prod = _lifetime_to_rows(prod_payload, "production")

    cons = {}
    try:
        cons_payload = _api_get(f"/systems/{sid}/consumption_lifetime")
        cons = _lifetime_to_rows(cons_payload, "consumption")
    except EnphaseError:
        # consumption monitoring may be off for some systems; production still works
        cons = {}

    all_dates = sorted(set(prod) | set(cons))
    rows = [(d, prod.get(d), cons.get(d)) for d in all_dates]
    if rows:
        db.upsert_daily_energy(rows)

    # keep system nameplate size fresh (for capacity-factor metric)
    try:
        summ = _api_get(f"/systems/{sid}/summary")
        if summ.get("size_w"):
            db.set_settings({"enphase_size_w": str(summ["size_w"])})
    except EnphaseError:
        pass

    db.set_settings({"last_sync": datetime.now().isoformat(timespec="seconds")})
    return {
        "system_id": sid,
        "days_production": len(prod),
        "days_consumption": len(cons),
        "latest_date": all_dates[-1] if all_dates else None,
    }
