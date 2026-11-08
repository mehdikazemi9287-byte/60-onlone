"""External credit providers (اعتبار خرید بیرونی): Tara, Digipay, SnappPay and similar.

The Tara pattern (docs/ROADMAP.md): a licensed bank/lender funds the purchase; 60Online is only the
accepting merchant. The buyer approves on the provider's page/app, the provider returns the browser
to our callback, and we verify the exact amount server-to-server before the order exists — the same
two-phase redirect contract as the Sepehr card gateway, so checkout needs no new code path.

The wire format below is a GENERIC merchant API (init → redirect → verify → cancel/refund). Each
provider's real field names and URLs come from its merchant contract and are mapped in
`FIELD_MAPS`; until a contract is signed these are provisional and the provider stays disabled
unless its env credentials are set (see `enabled_from_env`).
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Callable

from app.adapters.payment.sepehr import to_rial
from app.adapters.payment.base import (
    GatewayError, PaymentRequest, PaymentResult, PaymentStatus, RedirectInstruction,
    RedirectPaymentProvider, RefundResult,
)

Transport = Callable[[str, dict, dict], dict]

PROVIDERS = {
    # name: (Persian label, env prefix)
    "tara": ("اعتبار تارا", "TARA"),
    "digipay": ("اعتبار دیجی‌پی", "DIGIPAY"),
    "snapppay": ("اسنپ‌پی (اقساطی)", "SNAPPPAY"),
}

# Provisional: replace with the field names in each signed merchant API document.
FIELD_MAPS: dict[str, dict[str, str]] = {name: {} for name in PROVIDERS}


def _http_json(url: str, payload: dict, headers: dict) -> dict:
    if not url.startswith("https://"):
        raise GatewayError("credit provider URL must be https")
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - https enforced above
            return json.loads(resp.read().decode() or "{}")
    except Exception as exc:  # network, TLS, JSON
        raise GatewayError(f"credit provider unreachable: {exc.__class__.__name__}") from exc


class ExternalCreditProvider(RedirectPaymentProvider):
    """Generic redirect BNPL/credit merchant API."""

    def __init__(self, name: str, *, api_base: str, merchant_id: str, api_key: str,
                 transport: Transport | None = None):
        if name not in PROVIDERS and not name.startswith("mock"):
            raise ValueError(f"unknown external credit provider {name!r}")
        self.name = name
        self.label = PROVIDERS.get(name, ("اعتبار آزمایشی",))[0]
        self._base = api_base.rstrip("/")
        self._merchant = merchant_id
        self._key = api_key
        self._send = transport or _http_json

    def _f(self, field: str) -> str:
        return FIELD_MAPS.get(self.name, {}).get(field, field)

    def _call(self, path: str, payload: dict) -> dict:
        body = {self._f(k): v for k, v in payload.items()}
        return self._send(f"{self._base}/{path}", body, {"Authorization": f"Bearer {self._key}"})

    def initiate(self, request: PaymentRequest, *, invoice_id: int, callback_url: str) -> RedirectInstruction:
        try:
            amount_rial = to_rial(int(request.amount_minor), request.currency)
        except Exception as exc:
            raise GatewayError("credit providers settle in Rial") from exc
        res = self._call("purchase/init", {
            "merchant_id": self._merchant, "amount": amount_rial, "invoice_id": str(invoice_id),
            "order_reference": request.order_reference, "callback_url": callback_url,
            "idempotency_key": request.idempotency_key,
        })
        token, url = res.get(self._f("token")), res.get(self._f("redirect_url"))
        if not token or not isinstance(url, str) or not url.startswith("https://"):
            raise GatewayError(f"{self.name} refused the purchase: {res.get('message') or 'no token'}")
        return RedirectInstruction(url=url, method="GET", fields={}, provider=self.name, provider_ref=str(token))

    def verify(self, callback: dict, *, expected_amount_minor: int, currency: str) -> PaymentResult:
        token = callback.get(self._f("token")) or callback.get("token")
        if not token:
            return PaymentResult(PaymentStatus.FAILED, self.name, "", 0, currency, "missing_token")
        try:
            expected_rial = to_rial(int(expected_amount_minor), currency)
            res = self._call("purchase/verify", {"merchant_id": self._merchant, "token": str(token),
                                                  "amount": expected_rial})
        except GatewayError:
            return PaymentResult(PaymentStatus.FAILED, self.name, str(token), 0, currency, "verify_unreachable")
        amount = res.get(self._f("amount"))
        ok = res.get(self._f("status")) in ("approved", "settled", "paid", True)
        if not ok:
            return PaymentResult(PaymentStatus.FAILED, self.name, str(token), 0, currency, "declined")
        if type(amount) is not int or amount != expected_rial:
            # Never accept a different amount than the order total; the caller reverses it.
            return PaymentResult(PaymentStatus.FAILED, self.name, str(token), int(amount or 0), currency, "amount_mismatch")
        ref = str(res.get(self._f("reference")) or token)
        return PaymentResult(PaymentStatus.CAPTURED, self.name, ref, int(expected_amount_minor), currency)

    def reverse(self, callback: dict) -> bool:
        token = callback.get(self._f("token")) or callback.get("token")
        if not token:
            return False
        try:
            return bool(self._call("purchase/cancel", {"merchant_id": self._merchant, "token": str(token)}).get("ok"))
        except GatewayError:
            return False

    def refund(self, provider_ref: str, amount_minor: int, idempotency_key: str) -> RefundResult:
        res = self._call("purchase/refund", {"merchant_id": self._merchant, "reference": provider_ref,
                                             "amount_minor": int(amount_minor), "idempotency_key": idempotency_key})
        return RefundResult(status=PaymentStatus.REFUNDED if res.get("ok") else PaymentStatus.FAILED,
                            provider=self.name, provider_ref=str(res.get("refund_reference") or provider_ref),
                            amount_minor=int(amount_minor))

    @staticmethod
    def invoice_id_of(callback: dict) -> int | None:
        raw = callback.get("invoice_id") or callback.get("invoiceId") or callback.get("InvoiceId")
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None


def enabled_from_env(environ=os.environ) -> list[ExternalCreditProvider]:
    """Providers listed in EXTERNAL_CREDIT_PROVIDERS that have all three credentials set."""
    out = []
    for name in [n.strip() for n in environ.get("EXTERNAL_CREDIT_PROVIDERS", "").split(",") if n.strip()]:
        if name not in PROVIDERS:
            continue
        prefix = PROVIDERS[name][1]
        base, merchant, key = (environ.get(f"{prefix}_API_BASE"), environ.get(f"{prefix}_MERCHANT_ID"),
                               environ.get(f"{prefix}_API_KEY"))
        if base and merchant and key and base.startswith("https://"):
            out.append(ExternalCreditProvider(name, api_base=base, merchant_id=merchant, api_key=key))
    return out
