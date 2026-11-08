#!/usr/bin/env python3
"""Background jobs and self-monitoring for one production host (the `worker` service in deploy/docker-compose.prod.yml).

One process, no cron daemon needed. Every job is an existing idempotent script run as a subprocess, so a crash in one
job never takes the scheduler down and each job can still be run by hand (`python -m scripts.<name>`).

Monitoring: every 5 minutes it checks API readiness, the frontend, disk space and the age of the newest backup, and
sends an alert through a Bale/Telegram bot (ALERT_BOT_URL = https://tapi.bale.ai/bot<TOKEN>/sendMessage,
ALERT_CHAT_ID). Each alert repeats at most once an hour while the problem lasts, and a recovery message is sent.
"""
from __future__ import annotations

import datetime as _dt
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (script, every N seconds, at UTC hour or None)
JOBS = [
    ("run_partner_webhooks", 60, None),
    ("release_abandoned_payments", 300, None),
    ("run_recurring", 86_400, 3),        # 06:30 Tehran
    ("run_credit_cycle", 86_400, 1),
    ("expire_loyalty_coins", 86_400, 2),
    ("purge_personal_data", 86_400, 0),
]
CHECK_EVERY = 300
REALERT = 3600


def log(msg: str) -> None:
    print(f"{_dt.datetime.now(_dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}", flush=True)


def run(name: str) -> bool:
    try:
        p = subprocess.run([sys.executable, "-m", f"scripts.{name}"], cwd=ROOT, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        log(f"job {name}: TIMEOUT")
        return False
    out = (p.stdout.strip().splitlines() or [""])[-1]
    log(f"job {name}: exit={p.returncode} {out}")
    if p.returncode != 0:
        log((p.stderr or "")[-2000:])
    return p.returncode == 0


def notify(text: str) -> None:
    url, chat = os.environ.get("ALERT_BOT_URL"), os.environ.get("ALERT_CHAT_ID")
    log(f"ALERT {text}")
    if not (url and chat):
        return
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": f"[{os.environ.get('ALERT_HOST_NAME', '60online')}] {text}"}).encode()
        urllib.request.urlopen(url, data=data, timeout=10).read()
    except Exception as exc:  # noqa: BLE001 — alerting must never kill the scheduler
        log(f"alert send failed: {exc}")


def _http_ok(url: str) -> bool:
    try:
        return urllib.request.urlopen(url, timeout=8).status == 200
    except Exception:  # noqa: BLE001
        return False


def checks() -> dict[str, str | None]:
    """name → problem text (None = fine)."""
    out: dict[str, str | None] = {}
    api = os.environ.get("MONITOR_API_URL", "http://backend:8000/api/v1/health/ready")
    out["api"] = None if _http_ok(api) else f"API آماده نیست ({api})"
    web = os.environ.get("MONITOR_WEB_URL", "http://frontend:3000/")
    out["web"] = None if _http_ok(web) else f"سایت پاسخ نمی‌دهد ({web})"
    for path in filter(None, {os.environ.get("MEDIA_ROOT"), os.environ.get("BACKUP_DIR")}):
        if os.path.isdir(path):
            u = shutil.disk_usage(path)
            free = u.free / u.total
            out[f"disk:{path}"] = f"فضای دیسک {path} کم است: {free:.0%} آزاد" if free < 0.10 else None
    bdir = os.environ.get("BACKUP_DIR")
    if bdir and os.path.isdir(bdir):
        dumps = sorted(Path(bdir).glob("db-*.dump"), key=lambda p: p.stat().st_mtime)
        age_h = (time.time() - dumps[-1].stat().st_mtime) / 3600 if dumps else None
        out["backup"] = None if age_h is not None and age_h < 26 else \
            f"پشتیبان دیتابیس قدیمی است ({'هیچ' if age_h is None else f'{age_h:.0f} ساعت'})"
    return out


def main() -> int:
    last_run: dict[str, float] = {}
    last_day: dict[str, str] = {}
    open_problems: dict[str, float] = {}
    next_check = time.time() + 60  # let the stack start
    log("scheduler started")
    while True:
        now = time.time()
        utc = _dt.datetime.now(_dt.timezone.utc)
        for name, every, hour in JOBS:
            if hour is None:
                if now - last_run.get(name, 0) >= every:
                    last_run[name] = now
                    run(name)
            elif utc.hour >= hour and last_day.get(name) != utc.date().isoformat():
                last_day[name] = utc.date().isoformat()
                if not run(name):
                    notify(f"کار روزانهٔ {name} ناموفق بود؛ لاگ worker را ببینید")
        if now >= next_check:
            next_check = now + CHECK_EVERY
            for key, problem in checks().items():
                if problem and now - open_problems.get(key, 0) >= REALERT:
                    open_problems[key] = now
                    notify(problem)
                elif not problem and key in open_problems:
                    open_problems.pop(key)
                    notify(f"برطرف شد: {key}")
        time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
