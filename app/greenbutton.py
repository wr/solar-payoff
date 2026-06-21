"""Parse Eversource 'Green Button' exports into daily grid import (kWh) + cost.

Handles three shapes:
  - ESPI Atom XML (the standard 'Download My Data' format)
  - CSV (some portals offer it)
  - ZIP wrapping either of the above
"""
import csv
import io
import re
import zipfile
from collections import defaultdict
from datetime import datetime
import xml.etree.ElementTree as ET

ESPI_NS = "{http://naesb.org/espi}"


def parse_file(filename, content):
    """Return (rows, summary). rows = [(date, import_kwh, cost_or_None), ...]."""
    name = (filename or "").lower()
    if name.endswith(".zip") or content[:2] == b"PK":
        return _parse_zip(content)
    text_head = content[:512].lstrip()
    if text_head.startswith(b"<") or name.endswith(".xml"):
        return _parse_espi(content)
    return _parse_csv(content)


def _parse_zip(content):
    rows_all, summaries = {}, []
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            data = z.read(info)
            try:
                rows, summary = parse_file(info.filename, data)
            except Exception:
                continue
            for d, kwh, cost in rows:
                rows_all[d] = (d, kwh, cost)
            summaries.append(summary)
    rows = sorted(rows_all.values())
    return rows, _summarize(rows)


# ---- ESPI XML -------------------------------------------------------------

def _parse_espi(content):
    root = ET.fromstring(content)

    # ReadingType: powerOfTenMultiplier scales the raw value; default 0.
    multiplier = 0
    mt = root.find(f".//{ESPI_NS}ReadingType/{ESPI_NS}powerOfTenMultiplier")
    if mt is not None and mt.text:
        try:
            multiplier = int(mt.text)
        except ValueError:
            multiplier = 0
    scale = 10 ** multiplier

    daily_kwh = defaultdict(float)
    daily_cost = defaultdict(float)
    saw_cost = False

    for ir in root.iter(f"{ESPI_NS}IntervalReading"):
        tp = ir.find(f"{ESPI_NS}timePeriod")
        start_el = tp.find(f"{ESPI_NS}start") if tp is not None else None
        val_el = ir.find(f"{ESPI_NS}value")
        if start_el is None or val_el is None or not start_el.text or not val_el.text:
            continue
        start = int(start_el.text)
        d = datetime.fromtimestamp(start).date().isoformat()  # local tz (set TZ in container)
        wh = float(val_el.text) * scale          # value is in Wh
        daily_kwh[d] += wh / 1000.0

        cost_el = ir.find(f"{ESPI_NS}cost")
        if cost_el is not None and cost_el.text:
            saw_cost = True
            # ESPI cost is in 10^-5 of the currency unit
            daily_cost[d] += int(cost_el.text) / 100000.0

    rows = [
        (d, round(daily_kwh[d], 4), round(daily_cost[d], 2) if saw_cost else None)
        for d in sorted(daily_kwh)
    ]
    return rows, _summarize(rows)


# ---- CSV ------------------------------------------------------------------

def _find_col(fieldnames, *needles):
    for f in fieldnames:
        low = f.lower()
        if any(n in low for n in needles):
            return f
    return None


def _parse_csv(content):
    text = content.decode("utf-8-sig", errors="replace")
    # Some exports prepend metadata lines before the real header — find it.
    lines = text.splitlines()
    header_idx = 0
    for i, line in enumerate(lines):
        low = line.lower()
        if ("date" in low) and ("usage" in low or "kwh" in low or "consumption" in low):
            header_idx = i
            break
    reader = csv.DictReader(lines[header_idx:])
    fields = reader.fieldnames or []

    date_col = _find_col(fields, "date")
    usage_col = _find_col(fields, "usage", "kwh", "consumption")
    cost_col = _find_col(fields, "cost", "charge", "amount")
    units_col = _find_col(fields, "unit")

    daily_kwh = defaultdict(float)
    daily_cost = defaultdict(float)
    saw_cost = False

    for row in reader:
        if not date_col or not usage_col:
            break
        raw_date = (row.get(date_col) or "").strip()
        if not raw_date:
            continue
        # skip non-electric rows (e.g. gas in therms)
        if units_col and "therm" in (row.get(units_col) or "").lower():
            continue
        d = _norm_date(raw_date)
        if not d:
            continue
        try:
            daily_kwh[d] += float(re.sub(r"[^0-9.\-]", "", row[usage_col] or "0") or 0)
        except ValueError:
            continue
        if cost_col and row.get(cost_col):
            cleaned = re.sub(r"[^0-9.\-]", "", row[cost_col])
            if cleaned not in ("", "-", "."):
                saw_cost = True
                daily_cost[d] += float(cleaned)

    rows = [
        (d, round(daily_kwh[d], 4), round(daily_cost[d], 2) if saw_cost else None)
        for d in sorted(daily_kwh)
    ]
    return rows, _summarize(rows)


def _norm_date(s):
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    # try to salvage a leading YYYY-MM-DD or MM/DD/YYYY from datetime strings
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        mm, dd, yy = m.groups()
        return f"{yy}-{int(mm):02d}-{int(dd):02d}"
    return None


def _summarize(rows):
    if not rows:
        return {"days": 0, "first": None, "last": None, "total_kwh": 0, "has_cost": False}
    return {
        "days": len(rows),
        "first": rows[0][0],
        "last": rows[-1][0],
        "total_kwh": round(sum(r[1] for r in rows), 1),
        "has_cost": any(r[2] is not None for r in rows),
    }
