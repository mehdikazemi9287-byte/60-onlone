"""Outbound partner webhooks: subscriptions, emit(), signed delivery with retry + log.

Delivery is a separate, self-contained queue (webhook_deliveries) rather than the
connector outbox (integration_events): that outbox is keyed to connector_accounts
and its dispatcher hard-codes connector adapters. Semantics are the same — the
event row is written in the caller's transaction, HTTP happens later, outside
any transaction, with exponential backoff and a dead-letter state.

Wire format of each POST:
    Content-Type: application/json
    X-60Online-Event: <event_type>
    X-60Online-Delivery: <delivery id>
    X-60Online-Signature: t=<ts>,v1=<hex hmac_sha256(secret, f"{t}.{body}")>
    body = {"id": "evt_<id>", "type": ..., "created_at": ..., "data": {...}}
"""
from __future__ import annotations

import ipaddress
import json
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlsplit

from app.core import api_keys
from app.core.errors import NotFoundError, ValidationError

EVENT_TYPES: tuple[str, ...] = (
    "order.created", "order.status_changed", "offer.stock_low",
    "settlement.completed", "credit.statement_issued",
)
MAX_ATTEMPTS = 8
_BACKOFF_BASE = 30
_BACKOFF_CAP = 3600
_TIMEOUT_SECONDS = 10


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ------------------------------------------------------------------ SSRF guard
def _ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
                or addr.is_reserved or addr.is_unspecified or not addr.is_global)


def validate_webhook_url(url: str, *, allow_custom_port: bool = False,
                         resolver: Callable | None = None) -> str:
    """Refuse anything but https to a public host. Non-443 ports need admin override.

    The admin override relaxes only the port; private/loopback/link-local
    targets are always refused. Re-checked before every delivery (DNS rebinding).
    """
    if not isinstance(url, str) or len(url) > 2000:
        raise ValidationError("نشانی وب‌هوک نامعتبر است", code="webhook_url_invalid")
    parts = urlsplit(url.strip())
    if parts.scheme != "https":
        raise ValidationError("نشانی وب‌هوک باید https باشد", code="webhook_url_insecure")
    if parts.username or parts.password or not parts.hostname:
        raise ValidationError("نشانی وب‌هوک نامعتبر است", code="webhook_url_invalid")
    try:
        port = parts.port or 443
    except ValueError:
        raise ValidationError("درگاه نشانی وب‌هوک نامعتبر است", code="webhook_url_invalid")
    if port != 443 and not allow_custom_port:
        raise ValidationError("فقط درگاه ۴۴۳ مجاز است", code="webhook_port_forbidden")
    host = parts.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        raise ValidationError("نشانی داخلی برای وب‌هوک مجاز نیست", code="webhook_url_private")
    resolve = resolver or socket.getaddrinfo
    try:
        infos = resolve(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        raise ValidationError("نام میزبان وب‌هوک قابل تشخیص نیست", code="webhook_url_unresolvable")
    ips = {info[4][0] for info in infos}
    if not ips or not all(_ip_is_public(ip) for ip in ips):
        raise ValidationError("نشانی داخلی/خصوصی برای وب‌هوک مجاز نیست", code="webhook_url_private")
    return url.strip()


def _clean_events(raw) -> list[str]:
    if not isinstance(raw, list) or not raw or len(raw) > len(EVENT_TYPES):
        raise ValidationError("فهرست رویدادها نامعتبر است")
    bad = [e for e in raw if e not in EVENT_TYPES]
    if bad:
        raise ValidationError("رویداد ناشناخته", details={"unknown": bad, "allowed": list(EVENT_TYPES)})
    return sorted(set(raw))


# --------------------------------------------------------------- subscriptions
def subscription_dict(row) -> dict:
    d = dict(row)
    d["event_types"] = json.loads(d.pop("event_types_json") or "[]")
    d.pop("secret_salt", None)
    d["allow_custom_port"] = bool(d["allow_custom_port"])
    return d


def create_subscription(conn, *, client_id: int, url: str, event_types, master_key: str,
                        actor_user_id: int | None, allow_custom_port: bool = False,
                        resolver: Callable | None = None) -> dict:
    if not conn.execute("SELECT 1 FROM partner_api_clients WHERE id=?", (client_id,)).fetchone():
        raise NotFoundError("مشتری API یافت نشد")
    url = validate_webhook_url(url, allow_custom_port=allow_custom_port, resolver=resolver)
    events = _clean_events(event_types)
    salt = api_keys.new_salt()
    secret = api_keys.derive_signing_secret(master_key, salt)
    sid = conn.execute(
        """INSERT INTO webhook_subscriptions (client_id, url, event_types_json, secret_salt, secret_fingerprint,
               allow_custom_port, created_by_user_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
        (client_id, url, json.dumps(events), salt, api_keys.fingerprint(secret), 1 if allow_custom_port else 0,
         actor_user_id, _iso(_now()), _iso(_now()))).lastrowid
    out = subscription_dict(conn.execute("SELECT * FROM webhook_subscriptions WHERE id=?", (sid,)).fetchone())
    out["signing_secret"] = secret
    return out


def _subscription(conn, client_id: int, sub_id: int):
    row = conn.execute("SELECT * FROM webhook_subscriptions WHERE id=? AND client_id=?", (sub_id, client_id)).fetchone()
    if not row:
        raise NotFoundError("اشتراک وب‌هوک یافت نشد")
    return row


def update_subscription(conn, *, client_id: int, sub_id: int, data: dict,
                        resolver: Callable | None = None) -> dict:
    row = _subscription(conn, client_id, sub_id)
    allow = bool(data.get("allow_custom_port", row["allow_custom_port"]))
    url = row["url"]
    if "url" in data or "allow_custom_port" in data:
        url = validate_webhook_url(data.get("url", row["url"]), allow_custom_port=allow, resolver=resolver)
    events = _clean_events(data["event_types"]) if "event_types" in data else json.loads(row["event_types_json"])
    status = data.get("status", row["status"])
    if status not in ("active", "paused", "disabled"):
        raise ValidationError("وضعیت اشتراک نامعتبر است")
    conn.execute("""UPDATE webhook_subscriptions SET url=?, event_types_json=?, status=?, allow_custom_port=?, updated_at=?
                    WHERE id=?""", (url, json.dumps(events), status, 1 if allow else 0, _iso(_now()), sub_id))
    return subscription_dict(_subscription(conn, client_id, sub_id))


def rotate_subscription_secret(conn, *, client_id: int, sub_id: int, master_key: str) -> dict:
    _subscription(conn, client_id, sub_id)
    salt = api_keys.new_salt()
    secret = api_keys.derive_signing_secret(master_key, salt)
    conn.execute("UPDATE webhook_subscriptions SET secret_salt=?, secret_fingerprint=?, updated_at=? WHERE id=?",
                 (salt, api_keys.fingerprint(secret), _iso(_now()), sub_id))
    out = subscription_dict(_subscription(conn, client_id, sub_id))
    out["signing_secret"] = secret
    return out


def list_subscriptions(conn, client_id: int) -> list[dict]:
    return [subscription_dict(r) for r in conn.execute(
        "SELECT * FROM webhook_subscriptions WHERE client_id=? ORDER BY id", (client_id,)).fetchall()]


def list_deliveries(conn, *, client_id: int, sub_id: int, limit: int = 50) -> list[dict]:
    _subscription(conn, client_id, sub_id)
    rows = conn.execute(
        """SELECT d.*, e.event_type, e.event_key FROM webhook_deliveries d JOIN partner_webhook_events e ON e.id=d.event_id
           WHERE d.subscription_id=? ORDER BY d.id DESC LIMIT ?""", (sub_id, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["attempts"] = [dict(a) for a in conn.execute(
            "SELECT attempt_no, status_code, error, duration_ms, created_at FROM webhook_delivery_attempts WHERE delivery_id=? ORDER BY id",
            (r["id"],)).fetchall()]
        out.append(d)
    return out


# ------------------------------------------------------------------------ emit
def emit(conn, event_type: str, payload: dict, *, organization_ids=(), supplier_ids=(),
         event_key: str | None = None) -> int | None:
    """Record an event in the caller's transaction and queue one delivery per matching subscription.

    Audience: platform-owned clients receive every event; organization clients only
    events naming their organization; supplier clients only events naming their supplier.
    Returns the event id, or None when `event_key` was already emitted (idempotent).
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown partner event type: {event_type}")
    orgs = sorted({int(o) for o in organization_ids if o is not None})
    sups = sorted({int(s) for s in supplier_ids if s is not None})
    key = event_key or f"{event_type}:{api_keys.new_salt()}"
    if conn.execute("SELECT 1 FROM partner_webhook_events WHERE event_key=?", (key,)).fetchone():
        return None
    stamp = _iso(_now())
    event_id = conn.execute(
        "INSERT INTO partner_webhook_events (event_type, event_key, audience_json, payload_json, created_at) VALUES (?,?,?,?,?)",
        (event_type, key, json.dumps({"organization_ids": orgs, "supplier_ids": sups}),
         json.dumps(payload, ensure_ascii=False, default=str), stamp)).lastrowid
    subs = conn.execute(
        """SELECT s.id, s.event_types_json, c.owner_type, c.organization_id, c.supplier_id
           FROM webhook_subscriptions s JOIN partner_api_clients c ON c.id=s.client_id
           WHERE s.status='active' AND c.status='active'""").fetchall()
    for s in subs:
        if event_type not in json.loads(s["event_types_json"] or "[]"):
            continue
        if s["owner_type"] == "platform":
            pass
        elif s["owner_type"] == "organization" and s["organization_id"] in orgs:
            pass
        elif s["owner_type"] == "supplier" and s["supplier_id"] in sups:
            pass
        else:
            continue
        conn.execute("""INSERT INTO webhook_deliveries (subscription_id, event_id, status, next_attempt_at, created_at, updated_at)
                        VALUES (?,?, 'pending', ?, ?, ?)""", (s["id"], event_id, stamp, stamp, stamp))
    return event_id


def bridge_integration_events(db, *, limit: int = 200) -> int:
    """Turn checkout's existing ORDER_CREATED integration events into `order.created`.

    Checkout already writes ORDER_CREATED rows (integration_events) in its own
    transaction; this reads them by id cursor so checkout_service needs no edit.
    """
    emitted = 0
    with db.write_transaction() as conn:
        cur = conn.execute("SELECT last_id FROM partner_bridge_cursors WHERE name='order_created'").fetchone()
        last = int(cur["last_id"]) if cur else 0
        if cur is None:
            conn.execute("INSERT INTO partner_bridge_cursors (name, last_id) VALUES ('order_created', 0)")
        rows = conn.execute(
            """SELECT id, organization_id, payload_json FROM integration_events
               WHERE event_type='ORDER_CREATED' AND direction='outbound' AND id > ? ORDER BY id LIMIT ?""",
            (last, limit)).fetchall()
        for r in rows:
            last = int(r["id"])
            try:
                p = json.loads(r["payload_json"] or "{}")
                order_id = int(p["order_id"])
            except (ValueError, KeyError, TypeError):
                continue
            sups = [int(x["supplier_id"]) for x in conn.execute(
                "SELECT DISTINCT supplier_id FROM fulfillment_orders WHERE order_id=?", (order_id,)).fetchall()]
            data = {"order_id": order_id, "order_number": p.get("order_number"),
                    "status": p.get("status"), "total_minor": p.get("total_minor"),
                    "organization_id": r["organization_id"]}
            if emit(conn, "order.created", data, organization_ids=[r["organization_id"]], supplier_ids=sups,
                    event_key=f"order.created:{order_id}") is not None:
                emitted += 1
        conn.execute("UPDATE partner_bridge_cursors SET last_id=? WHERE name='order_created'", (last,))
    return emitted


# -------------------------------------------------------------------- delivery
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ARG002
        return None


def _http_send(url: str, body: bytes, headers: dict) -> int:
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with opener.open(req, timeout=_TIMEOUT_SECONDS) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def build_body(event_row) -> bytes:
    return json.dumps({"id": f"evt_{event_row['id']}", "type": event_row["event_type"],
                       "created_at": event_row["created_at"],
                       "data": json.loads(event_row["payload_json"])},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def deliver_due(db, *, master_key: str, sender: Callable | None = None, resolver: Callable | None = None,
                now: datetime | None = None, limit: int = 50) -> dict:
    """Deliver pending webhooks whose next_attempt_at is due. HTTP runs outside any transaction."""
    send = sender or _http_send
    current = now or _now()
    stats = {"delivered": 0, "retry": 0, "dead_letter": 0}
    with db.read_transaction() as conn:
        due = [dict(r) for r in conn.execute(
            """SELECT d.id, d.attempt_count, d.next_attempt_at FROM webhook_deliveries d
               WHERE d.status='pending' AND d.next_attempt_at <= ? ORDER BY d.next_attempt_at, d.id LIMIT ?""",
            (_iso(current), limit)).fetchall()]
    for d in due:
        lease = _iso(current + timedelta(seconds=_TIMEOUT_SECONDS * 3))
        with db.write_transaction() as conn:
            claimed = conn.execute(
                "UPDATE webhook_deliveries SET next_attempt_at=?, updated_at=? WHERE id=? AND status='pending' AND next_attempt_at=?",
                (lease, _iso(current), d["id"], d["next_attempt_at"])).rowcount
            if not claimed:
                continue
            row = conn.execute(
                """SELECT d.id, d.attempt_count, s.url, s.secret_salt, s.allow_custom_port, s.status AS sub_status,
                          e.id AS eid, e.event_type, e.created_at, e.payload_json
                   FROM webhook_deliveries d JOIN webhook_subscriptions s ON s.id=d.subscription_id
                   JOIN partner_webhook_events e ON e.id=d.event_id WHERE d.id=?""", (d["id"],)).fetchone()
        attempt = int(row["attempt_count"]) + 1
        status_code, error = None, None
        started = time.monotonic()
        try:
            if row["sub_status"] != "active":
                raise RuntimeError("subscription_inactive")
            validate_webhook_url(row["url"], allow_custom_port=bool(row["allow_custom_port"]), resolver=resolver)
            body = build_body({"id": row["eid"], "event_type": row["event_type"], "created_at": row["created_at"],
                               "payload_json": row["payload_json"]})
            secret = api_keys.derive_signing_secret(master_key, row["secret_salt"])
            headers = {"Content-Type": "application/json", "User-Agent": "60Online-Webhooks/1",
                       "X-60Online-Event": row["event_type"], "X-60Online-Delivery": str(row["id"]),
                       api_keys.SIGNATURE_HEADER: api_keys.sign(secret, body, int(current.timestamp()))}
            status_code = send(row["url"], body, headers)
            if not 200 <= int(status_code) < 300:
                error = f"http_{status_code}"
        except ValidationError as exc:
            error = f"url_refused:{exc.code}"
        except Exception as exc:  # network errors are recorded, never raised
            error = f"{type(exc).__name__}: {str(exc)[:200]}"
        duration = int((time.monotonic() - started) * 1000)
        with db.write_transaction() as conn:
            conn.execute("""INSERT INTO webhook_delivery_attempts (delivery_id, attempt_no, status_code, error, duration_ms, created_at)
                            VALUES (?,?,?,?,?,?)""", (row["id"], attempt, status_code, error, duration, _iso(current)))
            if error is None:
                conn.execute("""UPDATE webhook_deliveries SET status='delivered', attempt_count=?, last_status_code=?, last_error=NULL,
                                delivered_at=?, next_attempt_at=NULL, updated_at=? WHERE id=?""",
                             (attempt, status_code, _iso(current), _iso(current), row["id"]))
                stats["delivered"] += 1
            elif attempt >= MAX_ATTEMPTS:
                conn.execute("""UPDATE webhook_deliveries SET status='dead_letter', attempt_count=?, last_status_code=?, last_error=?,
                                next_attempt_at=NULL, updated_at=? WHERE id=?""",
                             (attempt, status_code, error, _iso(current), row["id"]))
                stats["dead_letter"] += 1
            else:
                delay = min(_BACKOFF_BASE * (2 ** (attempt - 1)), _BACKOFF_CAP)
                conn.execute("""UPDATE webhook_deliveries SET attempt_count=?, last_status_code=?, last_error=?, next_attempt_at=?,
                                updated_at=? WHERE id=?""",
                             (attempt, status_code, error, _iso(current + timedelta(seconds=delay)), _iso(current), row["id"]))
                stats["retry"] += 1
    return stats


def run_once(db, *, master_key: str, sender: Callable | None = None) -> dict:
    """One worker tick: bridge checkout events, then deliver what is due."""
    bridged = bridge_integration_events(db)
    stats = deliver_due(db, master_key=master_key, sender=sender)
    stats["bridged"] = bridged
    return stats
