"""Parse an Eversource statement (combined pdftotext -layout text of all pages)."""
import re, sys, subprocess, datetime as dt
from collections import defaultdict

MONTHS = {m: i for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}


def pdftext(path):
    return subprocess.run(["pdftotext", "-layout", path, "-"],
                          capture_output=True, text=True).stdout


def _mk(mon, day, year):
    return dt.date(year, MONTHS[mon[:3]], int(day))


def parse_front(text):
    out = {"purchase_kwh": 0.0, "sales_kwh": 0.0, "period_from": None,
           "period_to": None, "days": None, "statement_date": None, "net_charges": None}
    sd = None
    m = re.search(r"Statement Date:\s+([A-Za-z]{3})\w*\s+(\d{1,2})\s+(\d{4})", text)
    if m:
        sd = _mk(m.group(1), m.group(2), int(m.group(3)))
        out["statement_date"] = sd.isoformat()
    m = re.search(r"Total Current Charges\s+\$?([\d,]+\.\d{2})", text)
    out["net_charges"] = float(m.group(1).replace(",", "")) if m else None

    for line in text.splitlines():
        mm = re.search(
            r"([A-Za-z]{3})\s+(\d{1,2})\s+([A-Za-z]{3})\s+(\d{1,2})\s+(\d{1,3})\s+"
            r"[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d,]+)\s+(ONPK|OFFPK)\s+(PURCH|SALES)", line)
        if not mm:
            continue
        fmon, fday, tmon, tday, dy, hours, peak, kind = mm.groups()
        kwh = float(hours.replace(",", ""))
        out["purchase_kwh" if kind == "PURCH" else "sales_kwh"] += kwh
        out["days"] = int(dy)
        yr = sd.year if sd else 2000
        td = _mk(tmon, tday, yr)
        if sd and td > sd:
            td = _mk(tmon, tday, yr - 1)
        fd = _mk(fmon, fday, td.year)
        if fd > td:
            fd = _mk(fmon, fday, td.year - 1)
        out["period_from"], out["period_to"] = fd.isoformat(), td.isoformat()
    return out


# any per-kWh charge line: "<label> <NNN> KWH [X] $<rate> ..."
_LINE = re.compile(r"([A-Za-z][A-Za-z .,*/&'–-]*?)\s+([\d,]+)\s+KWH\s+X?\s*\$(-?[\d.]+)")


def parse_net(text):
    supply = defaultdict(list)     # peak -> [rates]
    deliv = defaultdict(float)     # peak -> summed rate
    peak_kwh = {}                  # peak -> kwh from supply line
    for line in text.splitlines():
        m = _LINE.search(line)
        if not m:
            continue
        label, kwh_s, rate_s = m.group(1), m.group(2), m.group(3)
        low = label.lower()
        if "peak" not in low:
            continue
        peak = "off" if ("off" in low) else "on"
        rate = float(rate_s)
        if "CR" in line and rate > 0:
            rate = -rate
        kwh = float(kwh_s.replace(",", ""))
        if ("supply" in low) or ("generation charge" in low):
            supply[peak].append(rate)
            peak_kwh[peak] = kwh
        else:
            deliv[peak] += rate
    if not supply:
        return {"supply_rate": None, "marginal_rate": None}
    num = den = 0.0
    for peak, srates in supply.items():
        srate = sum(srates) / len(srates)
        mr = srate + deliv.get(peak, 0.0)
        w = peak_kwh.get(peak, 0.0) or 1.0
        num += mr * w
        den += w
    marginal = num / den if den else None
    alls = [r for rs in supply.values() for r in rs]
    return {"supply_rate": round(sum(alls) / len(alls), 4),
            "marginal_rate": round(marginal, 4) if marginal else None}


if __name__ == "__main__":
    import json
    t = "\n".join(pdftext(p) for p in sys.argv[1:])
    r = parse_front(t); r.update(parse_net(t))
    print(json.dumps(r, indent=2))
