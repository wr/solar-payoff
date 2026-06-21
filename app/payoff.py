"""Payoff calculation — TOU, net-metering, fixed-charge-free avoided cost.

For each billing cycle, the value of your solar (the avoided cost) is:

    savings = production_on-peak  × rate_on-peak
            + production_off-peak × rate_off-peak

This equals (no-solar variable bill − actual variable bill), so the fixed
customer charge cancels out and never affects savings. Production's on/off-peak
split is taken from the meter's export split (the only metered signal of *when*
you generated). Energy is summed over the real billing-cycle dates.

Per day we apply that cycle's effective production-value rate
(eff = f_on·rate_on + (1−f_on)·rate_off) to that day's production, so the daily
series sums back to the per-cycle avoided cost.
"""
import json
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import db, config

CO2_KG_PER_KWH = 0.40
DEFAULT_FIXED = 9.62      # typical Eversource customer service charge, $/cycle


def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _build_tou_model(util, fallback_rate, onpeak_by_month=None, default_on=None, default_off=None):
    """Return (eff_for_date, cycles, stats). eff_for_date(d) -> production-value
    $/kWh for the cycle containing d (TOU-weighted), with seasonal fallback.

    onpeak_by_month: {month: fraction} measured from Enphase 15-min interval data
    (production in the on-peak window). When present it overrides the export-timing
    proxy. default_on/default_off: per-peak fallback $/kWh from the user's
    configured rate schedule (used when a cycle has no statement-parsed rate)."""
    onpeak_by_month = onpeak_by_month or {}
    if default_on is None:
        default_on = fallback_rate
    if default_off is None:
        default_off = fallback_rate
    cycles = []
    prev = None
    for r in util:
        end = r["date"]
        start = r["period_from"] or ((_d(prev) + timedelta(days=1)).isoformat()
                                     if prev else (_d(end) - timedelta(days=30)).isoformat())
        cycles.append({
            "start": start, "end": end,
            "rate_on": r.get("rate_on"), "rate_off": r.get("rate_off"),
            "frac": r.get("onpeak_frac"), "cost": r.get("cost"),
            "fixed": r.get("fixed_charge"),
        })
        prev = end

    # seasonal (by calendar month) + overall fallbacks for each component
    mon_on, mon_off, mon_frac = defaultdict(list), defaultdict(list), defaultdict(list)
    for c in cycles:
        mo = _d(c["end"]).month
        mon_on[mo].append(c["rate_on"]); mon_off[mo].append(c["rate_off"]); mon_frac[mo].append(c["frac"])
    ov_on = _avg([c["rate_on"] for c in cycles])
    ov_off = _avg([c["rate_off"] for c in cycles])
    ov_frac = _avg([c["frac"] for c in cycles]) or 0.4

    def comp(val, mon_map, mo, overall, default):
        if val is not None:
            return val
        return _avg(mon_map.get(mo, [])) or overall or default

    def eff_of(c):
        mo = _d(c["end"]).month
        # prefer interval-measured on-peak fraction; fall back to export proxy
        f = onpeak_by_month.get(str(mo))
        if f is None:
            f = comp(c["frac"], mon_frac, mo, ov_frac, 0.4)
        ron = comp(c["rate_on"], mon_on, mo, ov_on, default_on)
        roff = comp(c["rate_off"], mon_off, mo, ov_off, default_off)
        return f * ron + (1 - f) * roff

    for c in cycles:
        c["eff"] = eff_of(c)

    ov_eff = _avg([c["eff"] for c in cycles]) or fallback_rate
    mon_eff = defaultdict(list)
    for c in cycles:
        mon_eff[_d(c["end"]).month].append(c["eff"])

    def eff_for_date(ds):
        for c in cycles:
            if c["start"] <= ds <= c["end"]:
                return c["eff"]
        mo = _d(ds).month
        return _avg(mon_eff.get(mo, [])) or ov_eff

    effs = [c["eff"] for c in cycles]
    cal_avg = (sum(onpeak_by_month.values()) / len(onpeak_by_month)) if onpeak_by_month else None
    stats = {
        "eff_min": round(min(effs), 4) if effs else None,
        "eff_max": round(max(effs), 4) if effs else None,
        "eff_avg": round(ov_eff, 4) if ov_eff else None,
        "rate_on_avg": round(ov_on, 4) if ov_on else None,
        "rate_off_avg": round(ov_off, 4) if ov_off else None,
        "onpeak_frac_avg": round(cal_avg if cal_avg is not None else (ov_frac or 0), 3),
        "n_bills": len(cycles),
        "variable": len(set(round(e, 3) for e in effs)) > 1 if effs else False,
        "latest": round(cycles[-1]["eff"], 4) if cycles else None,
    }
    return eff_for_date, cycles, stats


def compute():
    energy = db.get_daily_energy()
    util = db.get_utility_daily()

    fallback_rate = config.retail_rate()
    net_cost = config.net_install_cost()
    metric = config.get_financials()["payoff_metric"]
    switchon = config.get_financials()["switchon_date"] or None

    try:
        onpeak_by_month = json.loads(db.get_setting("onpeak_frac_by_month", "{}") or "{}")
    except (ValueError, TypeError):
        onpeak_by_month = {}
    _fin = config.get_financials()

    def _fnum(x):
        try:
            return float(x)
        except (ValueError, TypeError):
            return None
    if _fin.get("rate_mode") == "tou":
        default_on = _fnum(_fin.get("tou_on_rate")) or fallback_rate
        default_off = _fnum(_fin.get("tou_off_rate")) or fallback_rate
    else:
        default_on = default_off = fallback_rate
    eff_for_date, cycles, rstats = _build_tou_model(
        util, fallback_rate, onpeak_by_month, default_on, default_off)

    daily = []
    monthly = defaultdict(lambda: {"production_kwh": 0.0, "consumption_kwh": 0.0,
                                   "savings": 0.0, "no_solar_cost": 0.0, "est_cost": 0.0})
    have_consumption = any(r["consumption_wh"] for r in energy)
    cons_c = prod_c = 0.0   # production vs consumption over days with consumption data

    for r in energy:
        d = r["date"]
        if switchon and d < switchon:
            continue
        prod = (r["production_wh"] or 0) / 1000.0
        cons = (r["consumption_wh"] or 0) / 1000.0
        eff = eff_for_date(d)

        savings = prod * eff                      # TOU avoided cost, fixed-charge-free
        no_solar = (cons if cons > 0 else prod) * eff
        est_cost = max(no_solar - savings, 0.0)

        daily.append({"date": d, "production_kwh": prod, "savings": savings})
        mm = monthly[d[:7]]
        mm["production_kwh"] += prod
        mm["consumption_kwh"] += cons
        mm["savings"] += savings
        mm["no_solar_cost"] += no_solar
        mm["est_cost"] += est_cost
        if cons > 0:
            cons_c += cons
            prod_c += prod

    # real net bill (ex fixed charge) per calendar month, from billing cycles
    real_exfixed_by_month = defaultdict(float)
    real_months = set()
    for c in cycles:
        if c["cost"] is not None:
            fixed = c["fixed"] if (c["fixed"] and 5 <= c["fixed"] <= 20) else DEFAULT_FIXED
            real_exfixed_by_month[c["end"][:7]] += max(c["cost"] - fixed, 0.0)
            real_months.add(c["end"][:7])

    daily.sort(key=lambda x: x["date"])
    cumulative, running = [], 0.0
    for rec in daily:
        running += rec["savings"]
        cumulative.append({"date": rec["date"], "cumulative_savings": round(running, 2)})

    total_saved = round(running, 2)
    lifetime_prod = round(sum(r["production_kwh"] for r in daily), 1)
    today = date.today()
    first_day = daily[0]["date"] if daily else None
    days_elapsed = (today - _d(first_day)).days + 1 if first_day else 0

    recent = daily[-365:] if len(daily) > 365 else daily
    avg_daily = (sum(r["savings"] for r in recent) / len(recent)) if recent else 0.0

    remaining = max(net_cost - total_saved, 0.0)
    pct_paid = round((total_saved / net_cost) * 100, 1) if net_cost > 0 else None

    breakeven_date = None
    already_paid_off = net_cost > 0 and total_saved >= net_cost
    if already_paid_off:
        for c in cumulative:
            if c["cumulative_savings"] >= net_cost:
                breakeven_date = c["date"]
                break
    elif avg_daily > 0 and net_cost > 0:
        breakeven_date = (today + timedelta(days=remaining / avg_daily)).isoformat()

    payoff_years = None
    if breakeven_date and first_day:
        payoff_years = round((_d(breakeven_date) - _d(first_day)).days / 365.25, 1)

    # ---- extra solar metrics --------------------------------------------
    years_elapsed = days_elapsed / 365.25 if days_elapsed else 0
    avg_annual_kwh = round(lifetime_prod / years_elapsed) if years_elapsed > 0.08 else None
    avg_power_w = round(lifetime_prod * 1000 / (days_elapsed * 24)) if days_elapsed else None
    pct_offset = round(prod_c / cons_c * 100) if cons_c > 0 else None
    try:
        size_w = float(db.get_setting("enphase_size_w") or 0)
    except (ValueError, TypeError):
        size_w = 0.0
    capacity_factor = round(avg_power_w / size_w * 100, 1) if (size_w and avg_power_w) else None
    specific_yield = round(avg_annual_kwh / (size_w / 1000)) if (size_w and avg_annual_kwh) else None
    try:
        pv_expected = float(db.get_setting("pv_expected_annual_kwh") or 0)
    except (ValueError, TypeError):
        pv_expected = 0.0
    performance_pct = round(avg_annual_kwh / pv_expected * 100) if (pv_expected and avg_annual_kwh) else None

    fin = config.get_financials()
    warranty = []
    wbase = switchon or first_day
    if wbase:
        bd = _d(wbase)
        for label, key in (("Panels", "panel_warranty_yr"),
                           ("Microinverters", "inverter_warranty_yr"),
                           ("Workmanship", "workmanship_warranty_yr")):
            try:
                term = int(float(fin.get(key) or 0))
            except (ValueError, TypeError):
                term = 0
            if term <= 0:
                continue
            try:
                exp = bd.replace(year=bd.year + term)
            except ValueError:  # leap-day base
                exp = bd.replace(year=bd.year + term, day=28)
            remaining = round((exp - today).days / 365.25, 1)
            warranty.append({"name": label, "term": term, "expires": exp.isoformat(),
                             "remaining_years": max(remaining, 0),
                             "pct_left": max(0.0, min(1.0, remaining / term))})

    # clear-sky potential: the system's own best-weather output per calendar month
    # (avg of top-3 days) scaled to a full year = a physical "max possible".
    DIM = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
    bymonth = defaultdict(list)
    for rec in daily:
        bymonth[int(rec["date"][5:7])].append(rec["production_kwh"])
    clear_day = {}
    for mo, vals in bymonth.items():
        top = sorted(vals, reverse=True)[:3]
        clear_day[mo] = sum(top) / len(top) if top else 0
    clearsky_annual = round(sum(clear_day.get(m, 0) * DIM[m] for m in range(1, 13))) if len(clear_day) >= 12 else None
    clearsky_capture = round(avg_annual_kwh / clearsky_annual * 100) if (clearsky_annual and avg_annual_kwh) else None

    projection = []
    if cumulative and avg_daily > 0 and not already_paid_off and net_cost > 0:
        last = cumulative[-1]
        last_date, val, step = _d(last["date"]), last["cumulative_savings"], 30
        projection.append({"date": last["date"], "cumulative_savings": round(val, 2)})
        guard = 0
        while val < net_cost and guard < 600:
            last_date += timedelta(days=step)
            val += avg_daily * step
            projection.append({"date": last_date.isoformat(), "cumulative_savings": round(val, 2)})
            guard += 1

    monthly_list = []
    for m in sorted(monthly.keys()):
        v = monthly[m]
        has_real = m in real_months
        monthly_list.append({
            "month": m,
            "production_kwh": round(v["production_kwh"], 1),
            "consumption_kwh": round(v["consumption_kwh"], 1),
            "savings": round(v["savings"], 2),
            "no_solar_cost": round(v["no_solar_cost"], 2),
            "actual_cost": round(real_exfixed_by_month[m] if has_real else v["est_cost"], 2),
            "actual_cost_is_real": has_real,
        })

    return {
        "headline": {
            "net_install_cost": round(net_cost, 2),
            "gross_install_cost": round(float(config.get_financials()["install_cost_gross"] or 0), 2),
            "incentives": round(float(config.get_financials()["incentives"] or 0), 2),
            "total_saved": total_saved,
            "remaining": round(remaining, 2),
            "pct_paid": pct_paid,
            "breakeven_date": breakeven_date,
            "payoff_years": payoff_years,
            "already_paid_off": already_paid_off,
            "avg_daily_savings": round(avg_daily, 2),
            "avg_monthly_savings": round(avg_daily * 30.44, 2),
            "lifetime_production_kwh": lifetime_prod,
            "avg_annual_production_kwh": avg_annual_kwh,
            "avg_power_w": avg_power_w,
            "pct_offset": pct_offset,
            "system_size_w": size_w or None,
            "capacity_factor": capacity_factor,
            "specific_yield": specific_yield,
            "clearsky_capture_pct": clearsky_capture,
            "clearsky_annual_kwh": clearsky_annual,
            "pv_expected_annual_kwh": round(pv_expected) if pv_expected else None,
            "performance_pct": performance_pct,
            "co2_avoided_kg": round(lifetime_prod * CO2_KG_PER_KWH, 0),
            "days_elapsed": days_elapsed,
            "first_date": first_day,
            "last_date": daily[-1]["date"] if daily else None,
            "rate_variable": rstats["variable"],
            "rate_min": rstats["eff_min"],
            "rate_max": rstats["eff_max"],
            "rate_avg": rstats["eff_avg"],
            "rate_latest": rstats["latest"],
            "rate_on_avg": rstats["rate_on_avg"],
            "rate_off_avg": rstats["rate_off_avg"],
            "onpeak_frac_avg": rstats["onpeak_frac_avg"],
            "onpeak_calibrated": bool(onpeak_by_month),
            "rate_fallback": fallback_rate,
            "n_bills": rstats["n_bills"],
            "tou": True,
            "metric": metric,
            "have_consumption": have_consumption,
        },
        "cumulative": cumulative,
        "projection": projection,
        "monthly": monthly_list,
        "warranty": warranty,
    }
