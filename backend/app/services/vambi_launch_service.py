"""آمادگی راه‌اندازی وامبی: launch readiness (read-only, comms plan section 2) and usage metrics (section 6).

Readiness never writes and never prints a secret: settings are reported only as set / unset (plus the price
visibility mode, which is public behaviour, not a secret).

"Comparable product" (کالای قابل مقایسه) = an active SKU with at least two DISTINCT active sellers whose offer
carries a valid verified price, using the same rule Vambi itself shows as a confirmed price
(storefront_service.offers_for → price_confirmed):
  offer active, supplier active, provenance allowed (real only outside COMMERCE_TEST_MODE),
  product/channel policy open (product_channel_policy.offer_sql), not expired (valid_until),
  pricing_mode fixed/bulk, selling_price_minor > 0, last_price_confirmed_at within the last 24 hours.
Stock is NOT required: a priced out-of-stock offer is still a price to compare.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os

from app.services import product_channel_policy as policy
from app.services import sale_eligibility as se

DEFAULT_MIN_COMPARABLE = 50
REQUIRED_MIGRATIONS = ("0079", "0080", "0082", "0083")
PRICE_FRESH_HOURS = se.MAX_CONFIRMATION_AGE_HOURS
log = logging.getLogger(__name__)


def min_comparable(env=None) -> int:
    env = os.environ if env is None else env
    try:
        return max(1, int(str(env.get("VAMBI_MIN_COMPARABLE", "")).strip() or DEFAULT_MIN_COMPARABLE))
    except ValueError:
        return DEFAULT_MIN_COMPARABLE


def _set(env, name: str) -> bool:
    return bool(str(env.get(name, "") or "").strip())


def comparable_products(conn) -> int:
    prov = ",".join(f"'{p}'" for p in se.allowed_provenance())
    row = conn.execute(f"""
        SELECT COUNT(*) FROM (
          SELECT so.product_id FROM seller_offers so JOIN suppliers s ON s.id = so.supplier_id
          WHERE so.status = 'active' AND s.status = 'active'
            AND so.provenance IN ({prov}) AND s.provenance IN ({prov})
            AND {policy.offer_sql('so.product_id', 'so.channel')}
            AND (so.valid_until IS NULL OR so.valid_until >= date('now'))
            AND so.pricing_mode IN ('fixed', 'bulk') AND so.selling_price_minor > 0
            AND so.last_price_confirmed_at IS NOT NULL
            AND datetime(so.last_price_confirmed_at) >= datetime('now', '-{PRICE_FRESH_HOURS} hours')
          GROUP BY so.product_id
          HAVING COUNT(DISTINCT so.supplier_id) >= 2
        ) comparable""").fetchone()
    return int(row[0])


def applied_migrations(conn, versions=REQUIRED_MIGRATIONS) -> set[str]:
    marks = ",".join("?" * len(versions))
    try:
        return {str(r[0]) for r in conn.execute(f"SELECT version FROM schema_migrations WHERE version IN ({marks})",
                                                tuple(versions))}
    except Exception:  # noqa: BLE001 — no migrations table yet means nothing is applied
        return set()


def readiness(conn, env=None) -> dict:
    """Every launch precondition that the code can check, each ok / not ok. Read-only."""
    env = os.environ if env is None else env
    checks: list[dict] = []

    def add(key, label_fa, ok, detail, **extra):
        checks.append({"key": key, "label_fa": label_fa, "ok": bool(ok), "detail": detail, **extra})

    threshold = min_comparable(env)
    n = comparable_products(conn)
    add("comparable_products", "کالای دارای دست‌کم دو فروشنده با قیمت تأییدشده", n >= threshold,
        f"{n} / {threshold}", value=n, threshold=threshold)
    sender = _set(env, "KAVENEGAR_SENDER")
    add("KAVENEGAR_SENDER", "خط پیامک کاوه‌نگار", sender, "set" if sender else "unset")
    vis_set = _set(env, "STOREFRONT_PRICE_VISIBILITY")
    from app.core.price_privacy import MODES
    raw = str(env.get("STOREFRONT_PRICE_VISIBILITY", "") or "").strip().lower()
    add("STOREFRONT_PRICE_VISIBILITY", "تصمیم نمایش قیمت (روی وامبی هم اعمال می‌شود)", vis_set and raw in MODES,
        ("set" if vis_set else "unset") + (f" ({raw})" if raw in MODES else (" (invalid)" if vis_set else "")),
        mode=raw if raw in MODES else None)
    origins, domain = _set(env, "SSO_ALLOWED_ORIGINS"), _set(env, "VAMBI_DOMAIN")
    add("SSO_ORIGINS", "ورود مشترک: SSO_ALLOWED_ORIGINS یا VAMBI_DOMAIN", origins or domain,
        f"SSO_ALLOWED_ORIGINS {'set' if origins else 'unset'}, VAMBI_DOMAIN {'set' if domain else 'unset'}")
    have = applied_migrations(conn)
    missing = [v for v in REQUIRED_MIGRATIONS if v not in have]
    add("migrations", "مهاجرت‌های هشدار قیمت و ورود مشترک", not missing,
        ("applied: " + ", ".join(REQUIRED_MIGRATIONS)) if not missing else ("missing: " + ", ".join(missing)),
        missing=missing)
    return {"ready": all(c["ok"] for c in checks), "checks": checks}


# ── usage metrics (سنجش استفاده, comms plan section 6) ────────────────────────
# First-party only. Searches and «مشاهده و خرید» clicks are daily numbers (no query text, user id or IP).
# Watches and alerts come from the price-alert tables. A Vambi order is an order placed while its buyer had a
# live Vambi referral (?ref=vambi on the product page, reported by the existing referral capture once signed in).

METRICS = ("search", "buy_click")
REF_CODE = "vambi"
REFERRAL_DAYS = 7
PRICE_UPDATE_WINDOW_H = 72
TEHRAN = _dt.timedelta(hours=3, minutes=30)  # Iran has had no DST since 2022
MAX_DAYS = 365


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(t: _dt.datetime) -> str:
    return t.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s) -> _dt.datetime | None:
    """Stored timestamps come as '2026-11-10T08:00:00Z', '...:00.123Z', '... +00:00' or '2026-11-10 08:00:00' (UTC)."""
    if not s:
        return None
    try:
        return _dt.datetime.strptime(str(s).replace(" ", "T")[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return None


def tehran_day(now: _dt.datetime | None = None) -> str:
    return ((now or _utcnow()).astimezone(_dt.timezone.utc) + TEHRAN).date().isoformat()


def bump(conn, metric: str, now: _dt.datetime | None = None) -> None:
    """Add one to today's counter. Stores the day, the metric name and a number — nothing else."""
    if metric not in METRICS:
        raise ValueError(metric)
    conn.execute("""INSERT INTO vambi_daily_counts (day, metric, n) VALUES (?, ?, 1)
                    ON CONFLICT (day, metric) DO UPDATE SET n = vambi_daily_counts.n + 1""", (tehran_day(now), metric))


def bump_safely(db, metric: str) -> None:
    """Counting must never break a search or a click."""
    try:
        with db.write_transaction() as conn:
            bump(conn, metric)
    except Exception:  # noqa: BLE001
        log.warning("vambi metric %s not counted", metric, exc_info=True)


def record_referral(conn, *, user_id: int, now: _dt.datetime | None = None) -> dict:
    t = now or _utcnow()
    conn.execute("INSERT INTO vambi_referrals (user_id, landed_at, expires_at) VALUES (?,?,?)",
                 (user_id, _iso(t), _iso(t + _dt.timedelta(days=REFERRAL_DAYS))))
    return {"recorded": True, "source": REF_CODE, "expires_in_days": REFERRAL_DAYS}


def attribute_order(conn, *, order_id: int, user_id: int, now: _dt.datetime | None = None) -> bool:
    """At order creation: link the order to the buyer's latest live Vambi referral, if any. Never raises."""
    stamp = _iso(now or _utcnow())
    conn.execute("SAVEPOINT vambi_attr")
    try:
        ref = conn.execute("""SELECT id FROM vambi_referrals WHERE user_id=? AND substr(landed_at,1,19)<=substr(?,1,19)
                                AND substr(expires_at,1,19)>=substr(?,1,19) ORDER BY id DESC LIMIT 1""",
                           (user_id, stamp, stamp)).fetchone()
        done = False
        if ref is not None:
            conn.execute("""INSERT INTO vambi_order_attributions (order_id, referral_id, created_at) VALUES (?,?,?)
                            ON CONFLICT (order_id) DO NOTHING""", (order_id, int(ref[0]), stamp))
            done = True
        conn.execute("RELEASE SAVEPOINT vambi_attr")
        return done
    except Exception:  # noqa: BLE001 — attribution is a metric; it must never fail an order
        conn.execute("ROLLBACK TO SAVEPOINT vambi_attr")
        conn.execute("RELEASE SAVEPOINT vambi_attr")
        log.warning("vambi order attribution skipped for order %s", order_id, exc_info=True)
        return False


def price_update_rate(conn, *, since: _dt.datetime, now: _dt.datetime) -> dict:
    """Share of «دیگر بهترین پیشنهاد نیستید» alerts followed by a price change by that seller on that product within
    72 hours. One alert = one (supplier, product, time) transition, however many of the seller's users were notified.
    A price change = an offer_price_history row for that seller's offer on that product. Alerts whose 72-hour window
    has not ended yet are reported as pending and left out of the rate."""
    window = _dt.timedelta(hours=PRICE_UPDATE_WINDOW_H)
    alerts = {}
    for r in conn.execute("""SELECT supplier_id, product_id, created_at FROM price_alert_events
                             WHERE alert_type='lost_best_offer' AND supplier_id IS NOT NULL
                               AND substr(created_at,1,19) >= ?""", (_iso(since)[:19],)):
        at = _parse(r["created_at"])
        if at is not None:
            alerts[(int(r["supplier_id"]), int(r["product_id"]), at)] = True
    done = [a for a in alerts if a[2] + window <= now]
    pending = len(alerts) - len(done)
    changes: dict[tuple[int, int], list[_dt.datetime]] = {}
    if done:
        first = min(a[2] for a in done)
        for r in conn.execute("""SELECT so.supplier_id, so.product_id, h.changed_at FROM offer_price_history h
                                 JOIN seller_offers so ON so.id = h.offer_id
                                 WHERE substr(h.changed_at,1,19) >= ?
                                   AND (h.old_price_minor IS NULL OR h.old_price_minor <> h.new_price_minor)""",
                              (_iso(first)[:19],)):
            t = _parse(r["changed_at"])
            if t is not None:
                changes.setdefault((int(r["supplier_id"]), int(r["product_id"])), []).append(t)
    followed = sum(1 for sid, pid, at in done if any(at < t <= at + window for t in changes.get((sid, pid), ())))
    return {"alerts": len(done), "followed_by_price_change": followed, "pending": pending,
            "rate": round(followed / len(done), 4) if done else None, "window_hours": PRICE_UPDATE_WINDOW_H}


def metrics(conn, *, days: int = 30, now: _dt.datetime | None = None) -> dict:
    now = now or _utcnow()
    days = max(1, min(MAX_DAYS, int(days)))
    first_day = tehran_day(now - _dt.timedelta(days=days - 1))
    since = now - _dt.timedelta(days=days)
    since_s = _iso(since)[:19]
    daily = {m: {} for m in METRICS}
    for r in conn.execute("SELECT day, metric, n FROM vambi_daily_counts WHERE day >= ? ORDER BY day", (first_day,)):
        if r["metric"] in daily:
            daily[r["metric"]][r["day"]] = int(r["n"])
    one = lambda sql, args=(): int(conn.execute(sql, args).fetchone()[0] or 0)  # noqa: E731
    by_type = {r["alert_type"]: int(r["n"]) for r in conn.execute(
        "SELECT alert_type, COUNT(*) AS n FROM price_alert_events WHERE substr(created_at,1,19) >= ? GROUP BY alert_type",
        (since_s,))}
    orders = conn.execute("""SELECT COUNT(*) AS n, COALESCE(SUM(o.total_minor), 0) AS total FROM vambi_order_attributions a
                             JOIN orders o ON o.id = a.order_id WHERE substr(a.created_at,1,19) >= ?""", (since_s,)).fetchone()
    return {
        "days": days, "from_day": first_day, "to_day": tehran_day(now),
        "searches": {"total": sum(daily["search"].values()),
                     "daily": [{"day": d, "count": n} for d, n in daily["search"].items()]},
        "buy_clicks": {"total": sum(daily["buy_click"].values()),
                       "daily": [{"day": d, "count": n} for d, n in daily["buy_click"].items()]},
        "watches": {"created": one("SELECT COUNT(*) FROM price_watches WHERE substr(created_at,1,19) >= ?", (since_s,)),
                    "active": one("SELECT COUNT(*) FROM price_watches WHERE active=1"),
                    "active_sms_off": one("SELECT COUNT(*) FROM price_watches WHERE active=1 AND sms_enabled=0")},
        "alerts": {"total": sum(by_type.values()), "by_type": by_type,
                   "sms_digests_sent": one("SELECT COUNT(*) FROM price_alert_sms WHERE status='sent' "
                                           "AND substr(created_at,1,19) >= ?", (since_s,)),
                   "sellers_sms_off": one("SELECT COUNT(*) FROM price_alert_user_prefs WHERE seller_sms=0")},
        "vambi_orders": {"referral_landings": one("SELECT COUNT(*) FROM vambi_referrals WHERE substr(landed_at,1,19) >= ?",
                                                  (since_s,)),
                         "orders": int(orders["n"]), "total_minor": int(orders["total"])},
        "seller_price_update": price_update_rate(conn, since=since, now=now),
    }
