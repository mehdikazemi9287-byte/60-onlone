"""آمادگی راه‌اندازی وامبی: launch readiness (read-only) for docs/vambi-comms-plan.md section 2.

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

import os

from app.services import product_channel_policy as policy
from app.services import sale_eligibility as se

DEFAULT_MIN_COMPARABLE = 50
REQUIRED_MIGRATIONS = ("0079", "0080", "0082")
PRICE_FRESH_HOURS = se.MAX_CONFIRMATION_AGE_HOURS


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
