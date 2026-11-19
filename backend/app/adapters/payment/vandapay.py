"""VandaPay (ونداپی) — «پرداخت با ونداپی» as a redirect payment method.

VandaPay is a credit gateway / payment orchestrator, not a PSP: on its page the customer pays one
order from organisation credit, gift cards, club credit and (for the rest) a bank card. For 60Online
it is one more ``RedirectPaymentProvider``, so checkout needs no new code path.

Merchant API (``vandapay`` repo, integrations/README.md and backend/CONTRACT-NOTES.md §B):
  POST /payment_intents             Idempotency-Key; {amount (integer rial), order_ref, return_url,
                                    category?, customer_phone?, items?[{sku, product_id, name, quantity,
                                    category, amount}] (sum(items.amount) == amount), metadata}
                                    → {id, status, amount, currency, mode, checkout_url}
  GET  /payment_intents/{id}        server-to-server truth (scoped to the key's mode: other mode → 404)
  POST /payment_intents/{id}/cancel
  POST /payment_intents/{id}/refunds  Idempotency-Key; {amount, reason}
  Webhook: header ``VandaPay-Signature: t=<unix>,v1=<hex>``,
           hex(HMAC_SHA256(webhook_secret, t + "." + raw_body)), 300 s tolerance, several v1 allowed.

Status golden rule: only succeeded / partially_refunded / refunded mean money was taken; failed /
expired / canceled mean it was not; everything else — including ``unknown`` and any status we do not
recognise — is *pending* and is never treated as success.

Safety rules in this adapter:
  * ``verify`` never trusts the browser: it reads the intent id that WE stored when the session was
    opened (``_provider_ref``, injected by checkout from the DB) and re-fetches the intent; it requires
    status ``succeeded``, the exact rial amount, currency IRR, no refunds, and the key's mode.
  * A pending intent raises ``GatewayError`` (checkout keeps the holds; the webhook finishes it later).
  * ``reverse`` acts only on that stored intent id, never on an id the browser sent.
  * Every write uses a deterministic Idempotency-Key, so a retry can never pay or refund twice.
  * Disabled unless configured from env (see ``enabled_from_env``); live keys only in production.
  * ``items`` are built by ``build_items`` with exact integer arithmetic: VAT is spread per line by the
    basis-points rule (``line_base * rate_bps // 10000``) and the rounding remainder goes on the largest
    line, so ``sum(items.amount) == amount`` always; a mismatch is refused before anything is sent.
  * Funding is exclusive (owner decision 2026-11-18, docs/decisions/2026-11-18-federated-credit-vandapay.md):
    an order paid with VandaPay carries the WHOLE total; 60Online never deducts its own welfare wallet or
    org credit for the same order, so one credit can never be spent in two ledgers.

The HTTP call is injectable so tests never touch the network.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from app.adapters.payment.base import (
    GatewayError, PaymentRequest, PaymentResult, PaymentStatus, RedirectInstruction,
    RedirectPaymentProvider, RefundResult,
)
from app.adapters.payment.sepehr import to_rial

log = logging.getLogger(__name__)

NAME = "vandapay"
LABEL = "پرداخت با ونداپی"
DEFAULT_API_BASE = "https://api.vandapay.ir/api/v1"
SIGNATURE_HEADER = "VandaPay-Signature"
WEBHOOK_TOLERANCE_SECONDS = 300
# Set by checkout from the DB (never by the browser): the VandaPay intent id we opened.
TRUSTED_REF_KEY = "_provider_ref"

PAID_STATUSES = frozenset({"succeeded", "partially_refunded", "refunded"})
FAILED_STATUSES = frozenset({"failed", "expired", "canceled"})
# Cancellable before the customer pays; anything else pending is left to VandaPay to settle.
CANCELLABLE_STATUSES = frozenset({"created", "requires_confirmation"})

# Category codes are VandaPay's taxonomy (vandapay migrations/0003_taxonomy.sql). The mapping from 60Online
# category slugs is an open decision (MASTER-PLAN «جدول نگاشت دسته»), so it is configuration, not code:
# VANDAPAY_CATEGORY_MAP='{"rice-grains":"goods.livelihood", ...}'. Unmapped slugs use the default item category.
DEFAULT_ORDER_CATEGORY = "goods"
DEFAULT_ITEM_CATEGORY = "goods.general"
SHIPPING_CATEGORY = "goods.general"
SHIPPING_SKU = "SHIPPING"
_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")
_PHONE_RE = re.compile(r"^09\d{9}$")


def _largest_index(values: list[int]) -> int:
    """Index of the largest value; ties go to the first line (deterministic)."""
    best = 0
    for i, v in enumerate(values):
        if v > values[best]:
            best = i
    return best


def _spread(total: int, weights: list[int]) -> list[int]:
    """Split ``total`` over ``weights`` proportionally with integer floors; remainder on the largest weight."""
    wsum = sum(weights)
    if not weights:
        return []
    if wsum <= 0:
        out = [0] * len(weights)
        out[_largest_index(weights)] = total
        return out
    out = [total * w // wsum for w in weights]
    out[_largest_index(weights)] += total - sum(out)
    return out


def line_vat(bases: list[int], *, tax_minor: int, rate_bps: int) -> list[int]:
    """Per-line VAT that adds up to the order's ``tax_minor`` exactly.

    Basis-points rule: ``vat_i = base_i * rate_bps // 10000``. If those floors already add up to the order
    VAT they are used as they are; otherwise, when the order VAT is the rule applied to the whole base, the
    remainder (always 0 < r < number of lines) goes on the largest line. When the order VAT is
    not the bps rule applied to the whole base (organisation exemption, a 0 rate, a pre-computed snapshot
    from another rule) the order's own ``tax_minor`` is spread in proportion instead — the invoice total
    is what was charged and must never be re-derived here.
    """
    if not bases:
        return []
    if tax_minor < 0 or rate_bps < 0:
        raise GatewayError("negative VAT cannot be sent to VandaPay")
    vat = [b * rate_bps // 10_000 for b in bases]
    remainder = tax_minor - sum(vat)
    if remainder == 0:
        return vat  # the order VAT IS the per-line rule (e.g. RFQ/PO: per item + shipping, each floored)
    if 0 < remainder < len(bases) and tax_minor == sum(bases) * rate_bps // 10_000:
        vat[_largest_index(bases)] += remainder
        return vat
    return _spread(tax_minor, bases)


def build_items(*, lines: list[dict], subtotal_minor: int, shipping_minor: int, tax_minor: int,
                tax_rate_bps: int, currency: str, category_map: dict | None = None,
                default_category: str = DEFAULT_ITEM_CATEGORY,
                shipping_category: str = SHIPPING_CATEGORY) -> list[dict]:
    """VandaPay ``items[]`` for one order, amounts in integer rial, VAT inside each line.

    ``lines`` are the order lines at their (pre-discount) line totals; ``subtotal_minor`` is the merchandise
    subtotal actually charged (after 60Coin / recurring discounts), so the discount is spread over the lines
    first, then VAT on the discounted bases. No separate "tax" line is ever sent (a category-limited credit
    would refuse it). Shipping is one extra line that carries its own VAT.

    VAT on shipping (owner decision 11, 2026-11-18): shipping is always VAT-chargeable, so the order's
    ``tax_minor`` covers merchandise AND shipping; the shipping amount is one more base in ``line_vat`` and the
    shipping line is ``shipping + its VAT``. ``sum(items.amount) == subtotal + shipping + tax`` still holds.
    """
    category_map = category_map or {}
    if not lines:
        raise GatewayError("an order without lines cannot be sent to VandaPay")
    gross = [int(l["line_total_minor"]) for l in lines]
    if any(g < 0 for g in gross) or subtotal_minor < 0 or shipping_minor < 0:
        raise GatewayError("negative line amounts cannot be sent to VandaPay")
    discount = sum(gross) - int(subtotal_minor)
    if discount < 0:
        raise GatewayError("order subtotal exceeds the sum of its lines")
    cut = _spread(discount, gross)
    bases = [g - c for g, c in zip(gross, cut)]
    if any(b < 0 for b in bases):
        raise GatewayError("discount larger than a line")
    ship = int(shipping_minor)
    all_bases = bases + ([ship] if ship > 0 else [])
    vat = line_vat(all_bases, tax_minor=int(tax_minor), rate_bps=int(tax_rate_bps))
    shipping_vat = vat[-1] if ship > 0 else 0
    items: list[dict] = []
    for line, base, v in zip(lines, bases, vat):
        amount = to_rial(base + v, currency)
        if amount <= 0:
            continue  # a fully discounted line carries no money
        slug = str(line.get("category_slug") or "")
        item = {"sku": str(line.get("sku") or line.get("product_id")), "name": str(line.get("title_fa") or "")[:200],
                "quantity": int(line.get("quantity") or 1), "category": category_map.get(slug, default_category),
                "amount": amount}
        if line.get("product_id") is not None:
            item["product_id"] = str(line["product_id"])
        items.append(item)
    if ship > 0:
        items.append({"sku": SHIPPING_SKU, "name": "هزینهٔ ارسال", "quantity": 1, "category": shipping_category,
                      "amount": to_rial(ship + shipping_vat, currency)})
    return items


def parse_category_map(raw: str | None) -> dict:
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise ValueError("VANDAPAY_CATEGORY_MAP must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError("VANDAPAY_CATEGORY_MAP must be a JSON object")
    for k, v in parsed.items():
        if not isinstance(k, str) or not isinstance(v, str) or not _CATEGORY_RE.match(v):
            raise ValueError(f"VANDAPAY_CATEGORY_MAP has an invalid entry for {k!r}")
    return dict(parsed)


# transport(method, url, headers, body_bytes_or_None) -> (http_status, parsed_json_dict)
Transport = Callable[[str, str, dict, "bytes | None"], "tuple[int, dict]"]


class VandaPayPending(GatewayError):
    """The intent is not final yet (processing / card_pending / unknown / …). Not a failure, not a success."""


class VandaPayAPIError(GatewayError):
    """VandaPay answered with a 4xx error body."""

    def __init__(self, status: int, code: str, message: str = ""):
        super().__init__(f"vandapay {status} {code}: {message}"[:300])
        self.status = status
        self.code = code


def _urllib_transport(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, dict]:
    if not url.startswith("https://"):
        raise GatewayError("VandaPay API URL must be https")
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - https enforced above
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, (exc.read() or b"")
    except Exception as exc:  # network, TLS, timeout
        raise GatewayError(f"vandapay unreachable: {exc.__class__.__name__}") from exc
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
    except (ValueError, UnicodeDecodeError):
        parsed = {}
    return status, parsed if isinstance(parsed, dict) else {}


def key_mode(secret_key: str) -> str:
    if secret_key.startswith("sk_live_"):
        return "live"
    if secret_key.startswith("sk_test_"):
        return "test"
    raise ValueError("VANDAPAY_SECRET_KEY must start with sk_test_ or sk_live_")


class VandaPayProvider(RedirectPaymentProvider):
    name = NAME
    label = LABEL

    def __init__(self, secret_key: str, *, webhook_secret: str, api_base: str = DEFAULT_API_BASE,
                 currency: str = "IRR", transport: Transport | None = None, category_map: dict | None = None,
                 order_category: str = DEFAULT_ORDER_CATEGORY,
                 default_item_category: str = DEFAULT_ITEM_CATEGORY) -> None:
        self.mode = key_mode(secret_key or "")
        for code in (order_category, default_item_category):
            if not _CATEGORY_RE.match(code or ""):
                raise ValueError(f"invalid VandaPay category code {code!r}")
        self.category_map = dict(category_map or {})
        self.order_category = order_category
        self.default_item_category = default_item_category
        if not webhook_secret:
            raise ValueError("VANDAPAY_WEBHOOK_SECRET is required")
        if not api_base.startswith("https://"):
            raise ValueError("VANDAPAY_API_BASE must be https")
        self._key = secret_key
        self._webhook_secret = webhook_secret
        self._base = api_base.rstrip("/")
        self.currency = currency
        self._send = transport or _urllib_transport

    # ------------------------------------------------------------------ http
    def _request(self, method: str, path: str, body: dict | None = None,
                 idempotency_key: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        status, parsed = self._send(method, self._base + path, headers, data)
        if 200 <= status < 300:
            return parsed
        if status == 429 or status >= 500:  # transient: outcome unknown, retry with the same key
            raise GatewayError(f"vandapay temporary error HTTP {status}")
        err = parsed.get("error") if isinstance(parsed.get("error"), dict) else {}
        raise VandaPayAPIError(status, str(err.get("code") or f"http_{status}"), str(err.get("message") or ""))

    def retrieve(self, intent_id: str) -> dict:
        if not intent_id or not isinstance(intent_id, str):
            raise ValueError("intent id required")
        return self._request("GET", f"/payment_intents/{urllib.parse.quote(intent_id, safe='')}")

    # -------------------------------------------------------------- initiate
    @staticmethod
    def initiate_key(order_reference: str, invoice_id: int) -> str:
        return f"60online-{order_reference}-invoice-{int(invoice_id)}"

    def open_intent(self, *, amount_rial: int, order_ref: str, return_url: str, metadata: dict,
                    idempotency_key: str, items: list[dict] | None = None, category: str | None = None,
                    customer_phone: str | None = None) -> tuple[str, str]:
        """POST /payment_intents with the amount checks; returns (intent_id, https checkout_url)."""
        if type(amount_rial) is not int or amount_rial <= 0:
            raise GatewayError("VandaPay amount must be a positive rial integer")
        body: dict = {"amount": amount_rial, "order_ref": order_ref, "return_url": return_url}
        if category:
            body["category"] = category
        if customer_phone and _PHONE_RE.match(customer_phone):
            body["customer_phone"] = customer_phone  # pre-fill only; VandaPay still runs its own OTP
        if items:
            if any(type(i.get("amount")) is not int or i["amount"] <= 0 for i in items):
                raise GatewayError("every VandaPay item needs a positive integer rial amount")
            if sum(i["amount"] for i in items) != amount_rial:
                raise GatewayError("vandapay items do not add up to the order amount")
            body["items"] = items
        body["metadata"] = metadata
        res = self._request("POST", "/payment_intents", body, idempotency_key=idempotency_key)
        intent_id, url = res.get("id"), res.get("checkout_url")
        if not isinstance(intent_id, str) or not intent_id or not isinstance(url, str) or not url.startswith("https://"):
            raise GatewayError("vandapay did not return an intent id and an https checkout_url")
        if res.get("mode") != self.mode:
            raise GatewayError(f"vandapay intent mode {res.get('mode')!r} does not match key mode {self.mode!r}")
        if res.get("amount") != amount_rial or res.get("currency", "IRR") != "IRR":
            raise GatewayError("vandapay intent amount/currency differs from the order")
        return intent_id, url

    def initiate(self, request: PaymentRequest, *, invoice_id: int, callback_url: str) -> RedirectInstruction:
        """Retail checkout. ``request.metadata["vandapay"]`` (set by checkout_service) may carry the order
        lines, VAT snapshot and verified phone; without it the intent is amount-only (old behaviour)."""
        amount_rial = to_rial(int(request.amount_minor), request.currency)  # GatewayError for other currencies
        if amount_rial <= 0:
            raise GatewayError("VandaPay amount must be a positive rial integer")
        sep = "&" if "?" in callback_url else "?"
        return_url = f"{callback_url}{sep}" + urllib.parse.urlencode({"invoice_id": int(invoice_id)})
        ctx = (request.metadata or {}).get("vandapay") or {}
        metadata = {"source": "60online", "invoice_id": str(int(invoice_id))}
        items = None
        if ctx.get("lines"):
            items = build_items(
                lines=ctx["lines"], subtotal_minor=int(ctx["subtotal_minor"]),
                shipping_minor=int(ctx.get("shipping_minor") or 0), tax_minor=int(ctx.get("tax_minor") or 0),
                tax_rate_bps=int(ctx.get("tax_rate_bps") or 0), currency=request.currency,
                category_map=self.category_map, default_category=self.default_item_category)
            metadata.update({
                "price_tier": str(ctx.get("price_tier") or "public"),  # label only; prices are 60Online's
                "vat_bps": int(ctx.get("tax_rate_bps") or 0),
                "vat_rial": to_rial(int(ctx.get("tax_minor") or 0), request.currency),
                "shipping_rial": to_rial(int(ctx.get("shipping_minor") or 0), request.currency),
                "funding": "vandapay_exclusive",
            })
        intent_id, url = self.open_intent(
            amount_rial=amount_rial, order_ref=request.order_reference, return_url=return_url, metadata=metadata,
            idempotency_key=self.initiate_key(request.order_reference, invoice_id), items=items,
            category=self.order_category if items else None, customer_phone=ctx.get("customer_phone"))
        return RedirectInstruction(url=url, method="GET", fields={}, provider=self.name, provider_ref=intent_id)

    # ---------------------------------------------------------------- verify
    @staticmethod
    def invoice_id_of(callback: dict) -> int | None:
        raw = callback.get("invoice_id")
        if raw is None or not re.fullmatch(r"\d{1,18}", str(raw).strip()):
            return None
        return int(str(raw).strip())

    def _failed(self, reason: str, ref: str, currency: str, amount_minor: int = 0) -> PaymentResult:
        return PaymentResult(PaymentStatus.FAILED, self.name, ref, amount_minor, currency, reason)

    def check_paid(self, ref: str, *, expected_amount_minor: int, currency: str,
                   metadata_match: dict) -> PaymentResult:
        """Re-fetch an intent WE opened and accept it only if succeeded, exact amount, IRR, no refunds, our
        mode and our metadata. Pending → ``VandaPayPending``; unreachable → ``GatewayError``."""
        expected_rial = to_rial(int(expected_amount_minor), currency)
        try:
            intent = self.retrieve(ref)  # GatewayError (unreachable / 5xx) propagates: holds are kept
        except VandaPayAPIError as exc:
            return self._failed(f"lookup_failed:{exc.code}", ref, currency)
        if intent.get("id") != ref:
            return self._failed("reference_mismatch", ref, currency)
        if intent.get("mode") != self.mode:
            return self._failed("mode_mismatch", ref, currency)
        meta = intent.get("metadata") if isinstance(intent.get("metadata"), dict) else {}
        for key, value in metadata_match.items():
            if value is None or str(meta.get(key)) != str(value):
                return self._failed("invoice_mismatch", ref, currency)
        status = intent.get("status")
        if status in FAILED_STATUSES:
            return self._failed(f"status_{status}", ref, currency)
        if status in ("partially_refunded", "refunded"):
            return self._failed("refunded_before_order", ref, currency)
        if status != "succeeded":
            raise VandaPayPending(f"vandapay intent {ref} is {status!r}, not final")
        amount = intent.get("amount")
        if type(amount) is not int or amount != expected_rial or intent.get("currency") != "IRR":
            return self._failed("amount_mismatch", ref, currency)
        if int(intent.get("refunded_amount") or 0) != 0:
            return self._failed("refunded_before_order", ref, currency)
        return PaymentResult(PaymentStatus.CAPTURED, self.name, ref, int(expected_amount_minor), currency)

    def verify(self, callback: dict, *, expected_amount_minor: int, currency: str) -> PaymentResult:
        ref = str(callback.get(TRUSTED_REF_KEY) or "").strip()
        if not ref:
            return self._failed("missing_reference", "", currency)
        invoice_id = self.invoice_id_of(callback)
        return self.check_paid(ref, expected_amount_minor=expected_amount_minor, currency=currency,
                               metadata_match={"invoice_id": invoice_id})

    # --------------------------------------------------------------- reverse
    def reverse(self, callback: dict) -> bool:
        """Give back a payment we cannot honour. Only ever acts on the intent id stored by us."""
        ref = str(callback.get(TRUSTED_REF_KEY) or "").strip()
        if not ref:
            log.warning("vandapay reverse without a stored intent id: nothing done")
            return False
        try:
            intent = self.retrieve(ref)
            if intent.get("mode") != self.mode:
                return False
            status = intent.get("status")
            if status in FAILED_STATUSES or status == "refunded":
                return True  # nothing taken / already given back
            if status in CANCELLABLE_STATUSES:
                res = self._request("POST", f"/payment_intents/{urllib.parse.quote(ref, safe='')}/cancel", {},
                                    idempotency_key=f"60online-{ref}-cancel")
                return res.get("status") == "canceled"
            if status in ("succeeded", "partially_refunded"):
                remaining = int(intent.get("amount") or 0) - int(intent.get("refunded_amount") or 0)
                if remaining <= 0:
                    return True
                res = self._request("POST", f"/payment_intents/{urllib.parse.quote(ref, safe='')}/refunds",
                                    {"amount": remaining, "reason": "60online: order could not be created"},
                                    idempotency_key=f"60online-{ref}-reverse-{remaining}")
                if res.get("status") == "succeeded":
                    return True
                log.warning("vandapay reverse refund for %s is %r (not final)", ref, res.get("status"))
                return False
            log.warning("vandapay reverse: intent %s is %r; left to VandaPay to settle", ref, status)
            return False
        except GatewayError:
            log.exception("vandapay reverse failed for intent %s", ref)
            return False

    def create_refund(self, intent_id: str, amount_minor: int, *, key: str, reason: str) -> dict:
        """POST /payment_intents/{id}/refunds with OUR deterministic Idempotency-Key.

        Returns {"id", "status": "succeeded" | "pending" | ..., "amount": rial}. VandaPay answers 201 when
        settled and 202 "pending" while the card leg is still being returned. 4xx → VandaPayAPIError
        (e.g. 422 partial_refund_unsupported / split_refund_manual_review: hand over to manual refund).
        """
        if not intent_id:
            raise ValueError("intent id required")
        amount_rial = to_rial(int(amount_minor), self.currency)
        if amount_rial <= 0:
            raise GatewayError("refund amount must be positive")
        res = self._request("POST", f"/payment_intents/{urllib.parse.quote(intent_id, safe='')}/refunds",
                            {"amount": amount_rial, "reason": reason[:200]}, idempotency_key=key)
        status = str(res.get("status") or "unknown")
        return {"id": str(res.get("id") or ""), "status": status, "amount": res.get("amount", amount_rial)}

    def refund(self, provider_ref: str, amount_minor: int, idempotency_key: str) -> RefundResult:
        res = self.create_refund(provider_ref, amount_minor, key=f"60online-{provider_ref}-refund-{idempotency_key}",
                                 reason="60online refund")
        ok = res["status"] == "succeeded"  # 202 "pending" is not reported as refunded
        return RefundResult(status=PaymentStatus.REFUNDED if ok else PaymentStatus.FAILED, provider=self.name,
                            provider_ref=res["id"] or provider_ref, amount_minor=int(amount_minor))

    # --------------------------------------------------------------- webhook
    def verify_webhook(self, raw_body: bytes, header: str | None, *, now: int | None = None) -> dict:
        """Check the signature on the RAW body and return the parsed event. Raises WebhookSignatureError."""
        verify_signature(raw_body, header, self._webhook_secret, now=now)
        try:
            event = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise WebhookSignatureError("malformed_body") from exc
        if not isinstance(event, dict):
            raise WebhookSignatureError("malformed_body")
        return event


class WebhookSignatureError(Exception):
    """reason: malformed_header | timestamp_out_of_tolerance | signature_mismatch | malformed_body"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


_TS_RE = re.compile(r"^\d{1,12}$")


def compute_signature(secret: str, timestamp: int, raw_body: bytes | str) -> str:
    body = raw_body.encode("utf-8") if isinstance(raw_body, str) else bytes(raw_body)
    msg = str(int(timestamp)).encode("ascii") + b"." + body
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_signature(raw_body: bytes | str, header: str | None, secret: str, *,
                     tolerance_seconds: int = WEBHOOK_TOLERANCE_SECONDS, now: int | None = None) -> int:
    """Same rules as the VandaPay SDKs (shared test vectors). Returns the signed timestamp."""
    if not secret:
        raise WebhookSignatureError("signature_mismatch")
    if not header or not isinstance(header, str):
        raise WebhookSignatureError("malformed_header")
    ts, sigs = None, []
    for part in header.split(","):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key, value = key.strip(), value.strip()
        if key == "t":
            if not _TS_RE.match(value):
                raise WebhookSignatureError("malformed_header")
            ts = int(value)
        elif key == "v1" and value:
            sigs.append(value)
    if ts is None or not sigs:
        raise WebhookSignatureError("malformed_header")
    current = int(time.time()) if now is None else int(now)
    if abs(current - ts) > tolerance_seconds:
        raise WebhookSignatureError("timestamp_out_of_tolerance")
    expected = compute_signature(secret, ts, raw_body).encode("ascii")
    ok = False
    for s in sigs:  # check every v1 (secret rotation); no early exit
        if hmac.compare_digest(expected, s.encode("utf-8")):
            ok = True
    if not ok:
        raise WebhookSignatureError("signature_mismatch")
    return ts


def enabled_from_env(environ=os.environ, *, app_env: str | None = None,
                     demo_mode: bool = False) -> VandaPayProvider | None:
    """The provider when fully configured, else None. Disabled by default.

    Needs VANDAPAY_SECRET_KEY and VANDAPAY_WEBHOOK_SECRET; VANDAPAY_API_BASE (https) is optional;
    VANDAPAY_ENABLED=0 switches it off. sk_live_ is refused unless APP_ENV=production, and sk_test_ is
    refused in production unless DEMO_MODE=1 (test money must never create real orders).
    """
    if str(environ.get("VANDAPAY_ENABLED", "1")).strip().lower() in ("0", "false", "no", "off"):
        return None
    key = (environ.get("VANDAPAY_SECRET_KEY") or "").strip()
    secret = (environ.get("VANDAPAY_WEBHOOK_SECRET") or "").strip()
    base = (environ.get("VANDAPAY_API_BASE") or DEFAULT_API_BASE).strip()
    if not key or not secret:
        return None
    env = app_env if app_env is not None else environ.get("APP_ENV", "development")
    try:
        mode = key_mode(key)
    except ValueError:
        log.error("VandaPay disabled: VANDAPAY_SECRET_KEY has an unknown prefix")
        return None
    if mode == "live" and env != "production":
        log.error("VandaPay disabled: sk_live_ key refused outside APP_ENV=production")
        return None
    if mode == "test" and env == "production" and not demo_mode:
        log.error("VandaPay disabled: sk_test_ key refused in production (set DEMO_MODE=1 for a demo server)")
        return None
    if not base.startswith("https://"):
        log.error("VandaPay disabled: VANDAPAY_API_BASE must be https")
        return None
    try:
        category_map = parse_category_map(environ.get("VANDAPAY_CATEGORY_MAP"))
        return VandaPayProvider(key, webhook_secret=secret, api_base=base,
                                currency=environ.get("CURRENCY", "IRR"), category_map=category_map,
                                order_category=(environ.get("VANDAPAY_ORDER_CATEGORY") or DEFAULT_ORDER_CATEGORY).strip(),
                                default_item_category=(environ.get("VANDAPAY_DEFAULT_ITEM_CATEGORY")
                                                       or DEFAULT_ITEM_CATEGORY).strip())
    except ValueError as exc:
        log.error("VandaPay disabled: %s", exc)
        return None


def org_cash_enabled(environ=os.environ) -> bool:
    """Second flag for paying an organisation order's cash share through VandaPay (default off)."""
    return str(environ.get("VANDAPAY_ORG_CASH_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")
