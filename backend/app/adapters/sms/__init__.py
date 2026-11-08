"""SMS senders for one-time codes. SMS_PROVIDER = console (dev/test, default) | kavenegar (production)."""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)


class SmsError(Exception):
    pass


class ConsoleSms:
    """Development sender: keeps the last code per phone in memory (tests read it) and logs a masked notice."""
    name = "console"
    outbox: dict[str, str] = {}

    def send_code(self, phone: str, code: str) -> None:
        ConsoleSms.outbox[phone] = code
        log.info("OTP for %s****%s issued (console sender)", phone[:4], phone[-2:])


class KavenegarSms:
    """Kavenegar verify/lookup API: template-based OTP (fast lane, allowed during ad-blocking hours)."""
    name = "kavenegar"

    def __init__(self, api_key: str, template: str, timeout: float = 8.0):
        if not api_key or not template:
            raise SmsError("KAVENEGAR_API_KEY و KAVENEGAR_TEMPLATE تنظیم نشده‌اند")
        self.api_key, self.template, self.timeout = api_key, template, timeout

    def send_code(self, phone: str, code: str) -> None:
        q = urllib.parse.urlencode({"receptor": phone, "token": code, "template": self.template})
        url = f"https://api.kavenegar.com/v1/{urllib.parse.quote(self.api_key, safe='')}/verify/lookup.json?{q}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=self.timeout) as r:  # noqa: S310 fixed host
                body = json.loads(r.read().decode() or "{}")
        except Exception as exc:  # network / HTTP error — never echo the key
            raise SmsError("ارسال پیامک ناموفق بود") from exc
        if (body.get("return") or {}).get("status") != 200:
            raise SmsError("ارسال پیامک ناموفق بود")


def sender_from_env():
    p = (os.environ.get("SMS_PROVIDER") or "console").strip().lower()
    if p == "kavenegar":
        return KavenegarSms(os.environ.get("KAVENEGAR_API_KEY", ""), os.environ.get("KAVENEGAR_TEMPLATE", ""))
    if p != "console":
        raise SmsError(f"SMS_PROVIDER ناشناخته: {p}")
    return ConsoleSms()
