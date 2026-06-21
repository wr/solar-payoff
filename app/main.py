"""FastAPI app: serves the dashboard SPA + JSON API."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, config, enphase, greenbutton, payoff, scheduler

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    config.ensure_defaults()
    scheduler.start()
    yield


app = FastAPI(title="Solar Payoff", lifespan=lifespan)


# ---- API models -----------------------------------------------------------

class FinancialsIn(BaseModel):
    install_cost_gross: str | None = None
    incentives: str | None = None
    switchon_date: str | None = None
    electricity_rate: str | None = None
    export_rate: str | None = None
    payoff_metric: str | None = None
    panel_warranty_yr: str | None = None
    inverter_warranty_yr: str | None = None
    workmanship_warranty_yr: str | None = None


class CredsIn(BaseModel):
    api_key: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    system_id: str | None = None


class ConnectIn(BaseModel):
    code: str


# ---- status / settings ----------------------------------------------------

@app.get("/api/status")
def status():
    api_key, client_id, client_secret = config.enphase_creds()
    energy = db.get_daily_energy()
    util = db.get_utility_daily()
    return {
        "enphase": {
            "creds_set": bool(api_key and client_id and client_secret),
            "connected": enphase.is_connected(),
            "system_id": db.get_setting("enphase_system_id"),
            "system_name": db.get_setting("enphase_system_name"),
            "last_sync": db.get_setting("last_sync"),
            "last_sync_error": db.get_setting("last_sync_error"),
            "redirect_uri": enphase.redirect_uri(),
        },
        "data": {
            "energy_days": len(energy),
            "energy_first": energy[0]["date"] if energy else None,
            "energy_last": energy[-1]["date"] if energy else None,
            "utility_days": len(util),
            "utility_first": util[0]["date"] if util else None,
            "utility_last": util[-1]["date"] if util else None,
        },
        "financials": config.get_financials(),
    }


@app.get("/api/settings")
def get_settings():
    return config.get_financials()


@app.post("/api/settings")
def save_settings(body: FinancialsIn):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        db.set_settings(updates)
    return config.get_financials()


@app.post("/api/enphase/credentials")
def save_credentials(body: CredsIn):
    updates = {}
    if body.api_key is not None:
        updates["enphase_api_key"] = body.api_key.strip()
    if body.client_id is not None:
        updates["enphase_client_id"] = body.client_id.strip()
    if body.client_secret is not None:
        updates["enphase_client_secret"] = body.client_secret.strip()
    if body.system_id is not None:
        updates["enphase_system_id"] = body.system_id.strip()
    if updates:
        db.set_settings(updates)
    return {"ok": True}


# ---- enphase oauth + sync -------------------------------------------------

@app.get("/api/enphase/authorize-url")
def enphase_authorize_url():
    try:
        url = enphase.authorize_url()
    except enphase.EnphaseError as e:
        raise HTTPException(400, str(e))
    return {"url": url, "redirect_uri": enphase.redirect_uri(),
            "manual": enphase.redirect_uri() == enphase.DEFAULT_REDIRECT}


@app.post("/api/enphase/connect")
def enphase_connect(body: ConnectIn):
    try:
        enphase.exchange_code(body.code)
        result = enphase.sync()
    except enphase.EnphaseError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "result": result}


@app.get("/api/enphase/callback")
def enphase_callback(code: str | None = None, error: str | None = None):
    if error or not code:
        return RedirectResponse(url="/?enphase=error")
    try:
        enphase.exchange_code(code)
        enphase.sync()
    except enphase.EnphaseError:
        return RedirectResponse(url="/?enphase=error")
    return RedirectResponse(url="/?enphase=connected")


@app.post("/api/enphase/sync")
def enphase_sync():
    result = scheduler.run_sync()
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "sync failed"))
    return result


# ---- green button ---------------------------------------------------------

@app.post("/api/greenbutton/upload")
async def greenbutton_upload(file: UploadFile = File(...)):
    content = await file.read()
    try:
        rows, summary = greenbutton.parse_file(file.filename, content)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not parse file: {e}")
    if not rows:
        raise HTTPException(400, "No usage rows found in that file.")
    db.upsert_utility_daily([{"date": d, "import_kwh": k, "cost": c} for (d, k, c) in rows])
    return {"ok": True, "summary": summary}


# ---- payoff ---------------------------------------------------------------

@app.get("/api/payoff")
def get_payoff():
    return payoff.compute()


# ---- static SPA -----------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
