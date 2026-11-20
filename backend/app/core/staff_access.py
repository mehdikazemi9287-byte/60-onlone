"""Scoped staff roles for internal teams (نقش‌های کارکنان داخلی).

Model
-----
* **Super-admin** is the existing platform role ``users.role = 'admin'``. Every
  admin account that existed before this change keeps full access with no data
  migration: "admin" *is* super-admin.
* **Staff roles** (finance, support, catalog, marketing, content, logistics) are
  rows in ``staff_role_assignments`` (migration 0083). A staff member keeps an
  ordinary ``users.role`` (usually ``employee``/``customer``) and gets access only
  to the admin endpoints of the areas their staff role covers.
* An admin-only endpoint (``require_auth("admin")``) is opened to a staff role
  only if a rule below lists that role for the endpoint's URL rule. Anything not
  listed stays super-admin only (fail closed): access/roles, users, platform
  settings, partner API keys, credit contracts, organizations, integrations.
* Endpoints shared by admin and supplier (``require_auth("admin", "supplier")``)
  are never opened to staff: their views branch on ``users.role``.

The rules match Flask URL-rule patterns (``request.url_rule.rule``), not raw
paths, so ``<int:id>`` segments are matched literally and cannot be spoofed.
"""
from __future__ import annotations

from typing import Iterable

STAFF_ROLES: dict[str, str] = {
    "finance": "مالی",
    "support": "پشتیبانی مشتریان",
    "catalog": "کاتالوگ و تأمین‌کنندگان",
    "marketing": "بازاریابی",
    "content": "محتوا و سئو",
    "logistics": "لجستیک و ارسال",
}
SUPER_ADMIN_LABEL = "مدیر ارشد (دسترسی کامل)"

ALL_STAFF = frozenset(STAFF_ROLES)
F, S, C, M, T, L = "finance", "support", "catalog", "marketing", "content", "logistics"
READ = frozenset({"GET"})

# (URL-rule prefix, methods or None for all, roles). First match wins, so the
# more specific prefixes come first. A prefix matches the rule itself or any
# rule below it ("/a/b" matches "/a/b" and "/a/b/<int:x>", not "/a/bc").
_RULES: tuple[tuple[str, frozenset[str] | None, frozenset[str]], ...] = (
    # Landing page and read-only reports
    ("/api/v1/admin/dashboard", READ, ALL_STAFF),
    ("/api/v1/admin/reports", READ, frozenset({F, M})),
    # Finance
    ("/api/v1/admin/suppliers/<int:supplier_id>/payables", None, frozenset({F})),
    ("/api/v1/admin/settlement-batches", None, frozenset({F})),
    ("/api/v1/admin/affiliate-payouts", None, frozenset({F})),
    ("/api/v1/admin/affiliates/<int:affiliate_id>/verify-sheba", None, frozenset({F})),
    ("/api/v1/admin/finance-formats", None, frozenset({F})),
    ("/api/v1/admin/finance-exports", None, frozenset({F})),
    ("/api/v1/admin/finance-mappings", None, frozenset({F})),
    ("/api/v1/admin/moadian", None, frozenset({F})),
    ("/api/v1/reconciliation", None, frozenset({F})),
    ("/api/v1/invoices/<int:invoice_id>/match", None, frozenset({F})),
    ("/api/v1/admin/preorders", None, frozenset({F})),
    ("/api/v1/admin/commission-rules", None, frozenset({F})),
    ("/api/v1/admin/shops/<int:supplier_id>/commission", None, frozenset({F})),
    ("/api/v1/admin/shops/<int:supplier_id>/verify-payout", None, frozenset({F})),
    ("/api/v1/admin/cashier-rules", None, frozenset({F})),
    ("/api/v1/admin/cashier/recurring", None, frozenset({F})),
    ("/api/v1/tax", None, frozenset({F})),
    ("/api/v1/admin/returns/<int:return_id>/refund-split", READ, frozenset({F, S})),
    ("/api/v1/admin/order-refunds", READ, frozenset({F, S})),
    ("/api/v1/admin/order-refunds", None, frozenset({F})),
    # Marketing
    ("/api/v1/admin/partner-discounts", None, frozenset({M})),
    ("/api/v1/loyalty/earn", None, frozenset({M})),
    ("/api/v1/admin/loyalty", None, frozenset({M})),
    ("/api/v1/admin/affiliate-rates", None, frozenset({M})),
    ("/api/v1/admin/packs", None, frozenset({M, C})),
    ("/api/v1/admin/notifications", None, frozenset({M, S})),
    # Content / SEO
    ("/api/v1/admin/content", None, frozenset({T})),
    ("/api/v1/admin/media/image-review", None, frozenset({C, T})),
    ("/api/v1/admin/media", None, frozenset({T, C})),
    # Logistics
    ("/api/v1/admin/fulfillment-orders", READ, frozenset({L, S})),
    ("/api/v1/admin/fulfillment-orders", None, frozenset({L})),
    ("/api/v1/admin/routing", None, frozenset({L})),
    ("/api/v1/admin/routing-exceptions", None, frozenset({L})),
    ("/api/v1/admin/carriers", None, frozenset({L})),
    ("/api/v1/admin/locations", None, frozenset({L})),
    ("/api/v1/admin/suppliers/<int:supplier_id>/locations", None, frozenset({L, C})),
    # Support
    ("/api/v1/admin/users/<int:uid>/unlock", None, frozenset({S})),
    ("/api/v1/admin/customers", READ, frozenset({S})),
    ("/api/v1/admin/orders", READ, frozenset({S, L, F})),
    ("/api/v1/admin/requests", None, frozenset({S})),
    ("/api/v1/admin/returns", READ, frozenset({S, F})),
    ("/api/v1/admin/returns", None, frozenset({S})),
    ("/api/v1/admin/procurement/cases", READ, frozenset({S})),
    ("/api/v1/exceptions", None, frozenset({S, L})),
    ("/api/v1/admin/b2b/applications", None, frozenset({S})),
    # Catalog and suppliers. Linking a login to a supplier is access control: super-admin only.
    ("/api/v1/admin/suppliers/<int:supplier_id>/user", None, frozenset()),
    ("/api/v1/admin/suppliers", READ, frozenset({C, S, F, L})),
    ("/api/v1/admin/suppliers", None, frozenset({C})),
    ("/api/v1/admin/catalog", None, frozenset({C})),
    ("/api/v1/admin/offer-review", None, frozenset({C})),
    ("/api/v1/admin/offers", None, frozenset({C})),
    ("/api/v1/admin/brand-registrations", None, frozenset({C})),
    ("/api/v1/admin/shop-applications", None, frozenset({C})),
    ("/api/v1/admin/shops/<int:supplier_id>/health", None, frozenset({C})),
    ("/api/v1/identifiers", None, frozenset({C})),
    ("/api/v1/price-sources", None, frozenset({C})),
    ("/api/v1/inventory-sources", None, frozenset({C})),
    ("/api/v1/scanner", None, frozenset({C})),
    ("/api/v1/import-jobs", None, frozenset({C})),
    ("/api/v1/erp-mappings", None, frozenset({C})),
    ("/api/v1/sync-runs", None, frozenset({C})),
)


def _prefix_match(rule: str, prefix: str) -> bool:
    return rule == prefix or rule.startswith(prefix + "/")


def roles_for_endpoint(rule: str | None, method: str) -> frozenset[str]:
    """Staff roles allowed on an admin-only endpoint; empty = super-admin only."""
    if not rule:
        return frozenset()
    method = (method or "").upper()
    for prefix, methods, roles in _RULES:
        if _prefix_match(rule, prefix) and (methods is None or method in methods):
            return roles
    return frozenset()


def active_staff_roles(conn, user_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT role FROM staff_role_assignments WHERE user_id = ? AND revoked_at IS NULL ORDER BY role",
        (user_id,),
    ).fetchall()
    return [r["role"] for r in rows if r["role"] in STAFF_ROLES]


def summary(role: str, staff_roles: Iterable[str]) -> dict:
    """What the frontend needs to show the admin shell (no secrets)."""
    staff_roles = sorted(set(staff_roles))
    return {
        "super_admin": role == "admin",
        "staff_roles": staff_roles,
        "is_staff": role == "admin" or bool(staff_roles),
    }
