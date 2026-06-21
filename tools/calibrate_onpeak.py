import sys,json,time,datetime as dt
sys.path.insert(0,"/app")
from app import enphase, db
sid=db.get_setting("enphase_system_id")
# on-peak window from settings (configured in the dashboard); defaults 12-20 Mon-Fri
def _i(k,d):
    try: return int(db.get_setting(k) or d)
    except (ValueError,TypeError): return d
ON_START=_i("onpeak_start",12); ON_END=_i("onpeak_end",20)
WEEKDAYS_ONLY=(db.get_setting("onpeak_days") or "weekdays")!="all"
today=dt.date.today()
on={}; off={}; cnt={}
day=today - dt.timedelta(days=365)
i=0
with open("/tmp/calib.log","w") as log:
    while day < today:
        start=int(dt.datetime(day.year,day.month,day.day).timestamp())
        ok=False; r=None
        for attempt in range(4):
            try:
                r=enphase._api_get(f"/systems/{sid}/telemetry/production_micro",
                                   {"granularity":"day","start_at":start})
                ok=True; break
            except Exception:
                time.sleep(8*(attempt+1))
        if ok and r:
            for itv in r.get("intervals",[]):
                t=dt.datetime.fromtimestamp(itv["end_at"])
                wh=itv.get("enwh",0) or 0
                onpk=(ON_START<=t.hour<ON_END) and (t.weekday()<5 or not WEEKDAYS_ONLY)
                if onpk: on[t.month]=on.get(t.month,0)+wh
                else: off[t.month]=off.get(t.month,0)+wh
            cnt[day.month]=cnt.get(day.month,0)+1
        i+=1
        log.write(f"{i} {day} ok={ok}\n"); log.flush()
        time.sleep(5)
        day+=dt.timedelta(days=5)
    frac={str(m):round(on.get(m,0)/(on.get(m,0)+off.get(m,0)),4)
          for m in range(1,13) if (on.get(m,0)+off.get(m,0))>0}
    db.set_settings({"onpeak_frac_by_month":json.dumps(frac),
                     "onpeak_frac_calib_days":json.dumps(cnt)})
    log.write("DONE "+json.dumps(frac)+"\n"); log.flush()
