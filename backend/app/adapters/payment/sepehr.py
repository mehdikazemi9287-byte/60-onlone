"""Sepehr Electronic Payment (پرداخت الکترونیک سپهر) internet payment gateway.

Flow (amounts are always in Rial):
  1. GetToken   POST {TerminalID, Amount, InvoiceID, callbackURL}  → {Status: 0, AccessToken}
  2. Browser    POST {TerminalID, token} to the payment page (/Pay)
  3. Callback   the gateway returns the browser to callbackURL with
                respcode, amount, invoiceid, digitalreceipt, terminalid, tracenumber, rrn, ...
  4. Advice     POST {digitalreceipt, Tid} → {Status: "Ok" | "Duplicate", ReturnId: <amount>}
                A payment is final for us only when Status is Ok/Duplicate AND ReturnId equals
                the amount we expected. Until Advice succeeds, the bank reverses the money itself.
  5. Rollback   POST {digitalreceipt, Tid} to give money back for a payment we cannot honour.

The HTTP call is injectable so tests never touch the network.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Callable

from app.adapters.payment.base import (
    GatewayError,
    PaymentRequest,
    PaymentResult,
    PaymentStatus,
    RedirectInstruction,
    RedirectPaymentProvider,
    RefundResult,
)

log = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://sepehr.shaparak.ir:8081/V1/PeymentApi"  # sic: the gateway's own spelling
DEFAULT_PAY_URL = "https://sepehr.shaparak.ir:8080/Pay"
MIN_AMOUNT_RIAL = 1000

HttpPost = Callable[[str, dict], dict]

# Negative ReturnId values on Advice/Rollback are errors; only -2 ("already reversed") is relied on here.
# Other codes are reported with the gateway's own Message; confirm them against the PSP's official guide.
ADVICE_ERRORS = {-2: "تراکنش قبلاً برگشت خورده است"}


def _post_json(url: str, payload: dict, timeout: float = 20.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https URL
            body = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GatewayError(f"sepehr unreachable: {exc}") from exc
    try:
        parsed = json.loads(body)
    except ValueError as exc:
        raise GatewayError(f"sepehr returned non-JSON: {body[:200]!r}") from exc
    if not isinstance(parsed, dict):
        raise GatewayError(f"sepehr returned unexpected JSON: {body[:200]!r}")
    return parsed


def _ci(d: dict, key: str):
    """Case-insensitive lookup: the gateway is not consistent about field casing."""
    lowered = key.lower()
    for k, v in d.items():
        if isinstance(k, str) and k.lower() == lowered:
            return v
    return None


def to_rial(amount_minor: int, currency: str) -> int:
    if currency == "IRR":
        return int(amount_minor)
    if currency == "IRT":
        return int(amount_minor) * 10
    raise GatewayError(f"Sepehr accepts Rial only; unsupported currency {currency!r}")


class SepehrPaymentProvider(RedirectPaymentProvider):
    name = "sepehr"

    def __init__(self, terminal_id: str, *, api_base: str = DEFAULT_API_BASE,
                 pay_url: str = DEFAULT_PAY_URL, http_post: HttpPost | None = None) -> None:
        if not terminal_id or not str(terminal_id).strip():
            raise ValueError("SEPEHR_TERMINAL_ID is required for the sepehr payment provider")
        self.terminal_id = str(terminal_id).strip()
        self.api_base = api_base.rstrip("/")
        self.pay_url = pay_url
        self._post = http_post or _post_json

    # ------------------------------------------------------------ initiate
    def initiate(self, request: PaymentRequest, *, invoice_id: int, callback_url: str) -> RedirectInstruction:
        amount = to_rial(request.amount_minor, request.currency)
        if amount < MIN_AMOUNT_RIAL:
            raise GatewayError(f"amount {amount} Rial is below the gateway minimum {MIN_AMOUNT_RIAL}")
        resp = self._post(f"{self.api_base}/GetToken", {
            "TerminalID": int(self.terminal_id) if self.terminal_id.isdigit() else self.terminal_id,
            "Amount": amount,
            "InvoiceID": int(invoice_id),
            "callbackURL": callback_url,
            "Payload": "",
        })
        status = _ci(resp, "Status")
        token = _ci(resp, "AccessToken")
        if str(status) != "0" or not token:
            raise GatewayError(f"sepehr GetToken refused: status={status!r}")
        return RedirectInstruction(
            url=self.pay_url, method="POST",
            fields={"TerminalID": self.terminal_id, "token": str(token)},
            provider=self.name, provider_ref=str(token),
        )

    # -------------------------------------------------------------- verify
    @staticmethod
    def invoice_id_of(callback: dict) -> int | None:
        raw = _ci(callback, "invoiceid")
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None

    def _failed(self, reason: str, amount_minor: int, currency: str, ref: str = "") -> PaymentResult:
        return PaymentResult(status=PaymentStatus.FAILED, provider=self.name, provider_ref=ref,
                             amount_minor=amount_minor, currency=currency, failure_reason=reason)

    def verify(self, callback: dict, *, expected_amount_minor: int, currency: str) -> PaymentResult:
        expected_rial = to_rial(expected_amount_minor, currency)
        receipt = str(_ci(callback, "digitalreceipt") or "").strip()
        respcode = str(_ci(callback, "respcode") or "").strip()
        if respcode != "0":
            msg = _ci(callback, "respmsg") or "پرداخت انجام نشد یا لغو شد"
            return self._failed(f"gateway respcode={respcode}: {msg}", expected_amount_minor, currency, receipt)
        terminal = str(_ci(callback, "terminalid") or "").strip()
        if terminal and terminal != self.terminal_id:
            return self._failed("callback terminal id does not match ours", expected_amount_minor, currency, receipt)
        try:
            paid_rial = int(str(_ci(callback, "amount")).strip())
        except (TypeError, ValueError):
            paid_rial = -1
        if paid_rial != expected_rial:
            return self._failed(f"amount mismatch: paid {paid_rial} expected {expected_rial}",
                                expected_amount_minor, currency, receipt)
        if not receipt:
            return self._failed("callback has no digital receipt", expected_amount_minor, currency)

        resp = self._post(f"{self.api_base}/Advice", {"digitalreceipt": receipt, "Tid": self.terminal_id})
        status = str(_ci(resp, "Status") or "").strip().lower()
        try:
            return_id = int(str(_ci(resp, "ReturnId")).strip())
        except (TypeError, ValueError):
            return_id = None
        if status in ("ok", "duplicate") and return_id == expected_rial:
            return PaymentResult(status=PaymentStatus.CAPTURED, provider=self.name, provider_ref=receipt,
                                 amount_minor=expected_amount_minor, currency=currency)
        reason = ADVICE_ERRORS.get(return_id, _ci(resp, "Message") or "تأیید پرداخت ناموفق بود")
        return self._failed(f"advice failed: status={status!r} returnId={return_id!r} ({reason})",
                            expected_amount_minor, currency, receipt)

    # ------------------------------------------------------------- reverse
    def reverse(self, callback: dict) -> bool:
        receipt = str(_ci(callback, "digitalreceipt") or "").strip()
        if not receipt or str(_ci(callback, "respcode") or "").strip() != "0":
            return True  # nothing was taken, nothing to give back
        try:
            resp = self._post(f"{self.api_base}/Rollback", {"digitalreceipt": receipt, "Tid": self.terminal_id})
        except GatewayError:
            log.exception("sepehr rollback unreachable for receipt %s", receipt)
            return False
        status = str(_ci(resp, "Status") or "").strip().lower()
        return_id = _ci(resp, "ReturnId")
        if status in ("ok", "duplicate") or str(return_id) == "-2":  # -2: already reversed
            return True
        log.error("sepehr rollback refused for receipt %s: %r", receipt, resp)
        return False

    def refund(self, provider_ref: str, amount_minor: int, idempotency_key: str) -> RefundResult:
        ok = self.reverse({"digitalreceipt": provider_ref, "respcode": "0"})
        return RefundResult(status=PaymentStatus.REFUNDED if ok else PaymentStatus.FAILED,
                            provider=self.name, provider_ref=provider_ref, amount_minor=amount_minor)
