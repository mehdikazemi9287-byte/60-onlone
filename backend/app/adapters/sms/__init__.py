"""SMS senders. SMS_PROVIDER = console (development/test only) | kavenegar (staging, production).

The console sender delivers nothing, so sender_from_env refuses it unless APP_ENV is development or test
(audit N1): on staging or production a missing provider is a clear error, never a fake "sent".

send_code: OTP through a verify template. send_text: plain notice text (price-alert digests) through the
provider's send API; Kavenegar needs KAVENEGAR_SENDER (the dedicated line number) for it.
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)


class SmsError(Exception):
    pass


class SmsOutcomeUnknown(SmsError):
    """The request may have reached the provider (read timeout, dropped connection, unreadable reply): the caller
    must record "unknown" and never retry blindly, or the user can get the same text twice."""


CONSOLE_ENVS = ("development", "test")
CONSOLE_TEXTS_KEPT = 1000


def console_allowed() -> bool:
    return (os.environ.get("APP_ENV") or "development").strip().lower() in CONSOLE_ENVS


class ConsoleSms:
    """Development sender: keeps the last code per phone in memory (tests read it) and logs a masked notice."""
    name = "console"
    outbox: dict[str, str] = {}
    texts: list[tuple[str, str]] = []  # (phone, text) of plain notices; tests read it, nothing leaves the process

    def send_code(self, phone: str, code: str) -> None:
        ConsoleSms.outbox[phone] = code
        log.info("OTP for %s****%s issued (console sender)", phone[:4], phone[-2:])

    def send_text(self, phone: str, text: str) -> None:
        ConsoleSms.texts.append((phone, text))
        del ConsoleSms.texts[:-CONSOLE_TEXTS_KEPT]  # bounded: a long-running dev process must not grow forever
        log.info("SMS notice for %s****%s queued (console sender)", phone[:4], phone[-2:])


class KavenegarSms:
    """Kavenegar verify/lookup API: template-based OTP (fast lane, allowed during ad-blocking hours)."""
    name = "kavenegar"

    def __init__(self, api_key: str, template: str, timeout: float = 8.0, sender: str = ""):
        if not api_key or not template:
            raise SmsError("KAVENEGAR_API_KEY و KAVENEGAR_TEMPLATE تنظیم نشده‌اند")
        self.api_key, self.template, self.timeout, self.sender = api_key, template, timeout, sender

    def send_text(self, phone: str, text: str) -> str | None:
        """Plain text through sms/send.json from the dedicated line (KAVENEGAR_SENDER). Returns the provider's
        message id once the provider has accepted the message."""
        if not self.sender:
            raise SmsError("KAVENEGAR_SENDER تنظیم نشده است")
        data = urllib.parse.urlencode({"receptor": phone, "sender": self.sender, "message": text}).encode()
        url = f"https://api.kavenegar.com/v1/{urllib.parse.quote(self.api_key, safe='')}/sms/send.json"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, method="POST"), timeout=self.timeout) as r:  # noqa: S310 fixed host
                raw = r.read().decode()
        except (TimeoutError, http.client.HTTPException) as exc:  # request sent, reply lost: outcome unknown
            raise SmsOutcomeUnknown("نتیجهٔ ارسال پیامک معلوم نیست") from exc
        except Exception as exc:  # connection refused / HTTP error status — never echo the key
            raise SmsError("ارسال پیامک ناموفق بود") from exc
        try:
            body = json.loads(raw or "{}")
        except ValueError as exc:
            raise SmsOutcomeUnknown("نتیجهٔ ارسال پیامک معلوم نیست") from exc
        if (body.get("return") or {}).get("status") != 200:
            raise SmsError("ارسال پیامک ناموفق بود")
        entries = body.get("entries") or []
        ref = entries[0].get("messageid") if entries and isinstance(entries[0], dict) else None
        return str(ref) if ref is not None else None

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
        return KavenegarSms(os.environ.get("KAVENEGAR_API_KEY", ""), os.environ.get("KAVENEGAR_TEMPLATE", ""),
                            sender=os.environ.get("KAVENEGAR_SENDER", ""))
    if p != "console":
        raise SmsError(f"SMS_PROVIDER ناشناخته: {p}")
    if not console_allowed():
        raise SmsError("SMS_PROVIDER=console فقط در development/test مجاز است؛ روی این سرور SMS_PROVIDER=kavenegar لازم است")
    return ConsoleSms()
