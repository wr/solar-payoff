"""Fetch expected annual production from PVWatts and store it for the Performance
metric (settings key pv_expected_annual_kwh).

Run inside the container:
    docker exec solar-payoff python3 /tmp/fetch_pvwatts.py

Edit the SITE constants below for your array, or set pv_lat/pv_lon/pv_tilt/
pv_azimuth (and enphase_size_w) in settings and they'll be used instead.

NOTE: NREL was renamed (National Laboratory of the Rockies); developer.nrel.gov
was retired 2026-05-29 -> use developer.nlr.gov. Get a free key at
developer.nlr.gov; DEMO_KEY is rate-limited.
"""
import json, urllib.request, sys
sys.path.insert(0, "/app")
from app import db

# --- edit these for your array (or set them in settings) ---
LAT, LON = 40.0, -75.0      # your latitude / longitude
TILT, AZIMUTH = 30, 180     # roof pitch (deg) / facing (deg, 180 = due south)
LOSSES = 14                 # PVWatts default system losses (%)
API_KEY = "DEMO_KEY"        # replace with your developer.nlr.gov key
# -----------------------------------------------------------

s = db.get_all_settings()
lat = float(s.get("pv_lat") or LAT)
lon = float(s.get("pv_lon") or LON)
tilt = float(s.get("pv_tilt") or TILT)
az = float(s.get("pv_azimuth") or AZIMUTH)
cap_kw = (float(s.get("enphase_size_w") or 0) / 1000) or 9.0
key = s.get("nlr_api_key") or API_KEY

url = (f"https://developer.nlr.gov/api/pvwatts/v8.json?api_key={key}"
       f"&lat={lat}&lon={lon}&system_capacity={cap_kw}&azimuth={az}"
       f"&tilt={tilt}&array_type=1&module_type=0&losses={LOSSES}")
d = json.load(urllib.request.urlopen(url, timeout=30))
if d.get("errors"):
    print("API errors:", d["errors"]); sys.exit(1)
ann = round(d["outputs"]["ac_annual"])
db.set_settings({"pv_expected_annual_kwh": str(ann), "pv_tilt": str(tilt), "pv_azimuth": str(az)})
print(f"stored pv_expected_annual_kwh = {ann} ({ann/cap_kw:.0f} kWh/kW/yr)")
