"""Daily background sync of Enphase data."""
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from . import enphase, db

log = logging.getLogger("solar.scheduler")
_scheduler = None


def run_sync():
    """Safe wrapper: records success/error in settings so the UI can show it."""
    if not enphase.is_connected():
        return {"ok": False, "error": "not connected"}
    try:
        result = enphase.sync()
        db.set_settings({"last_sync_error": ""})
        log.info("Enphase sync ok: %s", result)
        return {"ok": True, "result": result}
    except Exception as e:  # noqa: BLE001 - want any failure surfaced, not crashed
        db.set_settings({"last_sync_error": f"{datetime.now().isoformat(timespec='seconds')}: {e}"})
        log.exception("Enphase sync failed")
        return {"ok": False, "error": str(e)}


def start():
    global _scheduler
    if _scheduler:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    # Daily at 06:15. Enphase lifetime data settles overnight.
    _scheduler.add_job(run_sync, "cron", hour=6, minute=15, id="daily_sync",
                       misfire_grace_time=3600, coalesce=True)
    _scheduler.start()
    log.info("Scheduler started")
