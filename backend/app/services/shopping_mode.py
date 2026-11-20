"""Shopping modes (owner decision 2026-11-19): «شخصی | پرسنل سازمان | سازمانی و عمده».

Rules this module enforces on the SERVER (the client only says which mode it is in):

* ``personal`` is the default for everyone and is always allowed. A request that names no mode is personal,
  so an old client keeps working against the personal cart.
* ``staff`` needs an active membership (any role) in an active organization.
* ``org`` («سازمانی و عمده») is open to every signed-in buyer: hotels, mosques/heyats, ceremonies and charities
  buy in bulk without being a member of a contracted organization (megamarket brief 2026-11-19). It is a
  separate, buyer-paid cart; organization tools (RFQ, pro-forma approval, org credit) keep their own checks.
* Every mode has its own active cart (carts.shopping_mode, migration 0084). Items added in one mode never
  appear in, and are never checked out from, another mode's cart.
* Employer money — organization credit allocations and the welfare wallet — is a staff benefit: it is applied
  only to the ``staff`` cart. ``personal`` and ``org`` carts are paid by the buyer (card / gateway).

Switching modes is free: it changes nothing on the server. A user who is not (or no longer) eligible for a
mode can still READ that mode's cart; adding to it, quoting it and checking it out are refused with 403
``shopping_mode_not_allowed``.
"""
from __future__ import annotations

import sqlite3

from app.core.errors import PermissionError_, ValidationError

PERSONAL, STAFF, ORG = "personal", "staff", "org"
MODES = (PERSONAL, STAFF, ORG)
LABELS = {PERSONAL: "شخصی", STAFF: "پرسنل سازمان", ORG: "سازمانی و عمده"}
HEADER = "X-Shopping-Mode"
MANAGER_ROLES = ("organization_admin", "procurement_agent", "organization_finance")


def parse(value) -> str:
    """Validate a client-supplied mode. None/empty → personal (backward compatible)."""
    if value is None:
        return PERSONAL
    if not isinstance(value, str):
        raise ValidationError("حالت خرید نامعتبر است", code="invalid_shopping_mode",
                              details={"shopping_mode": "یکی از personal، staff یا org"})
    value = value.strip().lower()
    if not value:
        return PERSONAL
    if value not in MODES:
        raise ValidationError("حالت خرید نامعتبر است", code="invalid_shopping_mode",
                              details={"shopping_mode": "یکی از personal، staff یا org"})
    return value


def from_request(body: dict | None = None) -> str:
    """Mode of the current request: body ``shopping_mode`` > ``X-Shopping-Mode`` header > ``?mode=`` > personal."""
    from flask import request
    if isinstance(body, dict) and body.get("shopping_mode") is not None:
        return parse(body.get("shopping_mode"))
    header = request.headers.get(HEADER)
    if header is not None and header.strip():
        return parse(header)
    return parse(request.args.get("mode"))


def access(conn: sqlite3.Connection, user_id: int, mode: str) -> dict:
    """{"mode", "allowed", "reason", "organization_id"} — read-only, from live membership rows."""
    if mode == PERSONAL:
        return {"mode": mode, "allowed": True, "reason": None, "organization_id": None}
    roles = MANAGER_ROLES if mode == ORG else ("employee",) + MANAGER_ROLES
    marks = ",".join("?" * len(roles))
    row = conn.execute(
        f"""SELECT m.organization_id FROM organization_memberships m
            JOIN organizations o ON o.id = m.organization_id AND o.status = 'active'
            WHERE m.user_id = ? AND m.status = 'active' AND m.role IN ({marks})
            ORDER BY m.id LIMIT 1""",
        (user_id, *roles),
    ).fetchone()
    if row is not None:
        return {"mode": mode, "allowed": True, "reason": None, "organization_id": int(row["organization_id"])}
    if mode == ORG:
        return {"mode": mode, "allowed": True, "reason": None, "organization_id": None}
    return {"mode": mode, "allowed": False, "organization_id": None,
            "reason": "خرید پرسنلی فقط برای عضو فعال یک سازمان طرف قرارداد در دسترس است"}


def require(conn: sqlite3.Connection, user_id: int, mode: str) -> dict:
    state = access(conn, user_id, mode)
    if not state["allowed"]:
        raise PermissionError_(state["reason"], code="shopping_mode_not_allowed",
                               details={"shopping_mode": mode})
    return state


def employer_funding_allowed(mode: str) -> bool:
    """Organization credit and welfare wallet are staff benefits."""
    return mode == STAFF
