"""Credit eligibility rules.

Business rules live here, not in route handlers. Each rule is a small callable
that inspects a `CreditContext` and returns zero or more `Restriction`s. A
restriction either **blocks** credit entirely or **caps** the usable amount.

Adding a rule later (a blocked-supplier rule, a weekend rule, a per-department
rule) means appending one function to `RULES` — no call site changes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

# ---------------------------------------------------------------- vocabulary
BLOCK = "block"
CAP = "cap"


@dataclass(frozen=True)
class Restriction:
    code: str
    message: str
    kind: str = BLOCK          # BLOCK or CAP
    cap_minor: int | None = None   # only meaningful when kind == CAP

    def to_dict(self) -> dict:
        data = {"code": self.code, "message": self.message, "kind": self.kind}
        if self.cap_minor is not None:
            data["cap_minor"] = self.cap_minor
        return data


@dataclass
class CartLine:
    product_id: int
    title_fa: str
    sku: str
    category_slug: str
    unit_price_minor: int
    quantity: int
    line_total_minor: int


@dataclass
class CreditContext:
    """Everything a rule may look at. Rules must not touch the database."""

    now: datetime
    organization_status: str
    membership_status: str
    membership_role: str
    allocation_status: str
    allocated_minor: int
    available_minor: int
    valid_from: str | None
    expires_at: str | None
    category_slugs: list[str] | None
    per_transaction_limit_minor: int | None
    period_limit_minor: int | None
    period_consumed_minor: int
    lines: list[CartLine]
    shipping_fee_minor: int
    subtotal_minor: int
    tax_minor: int = 0
    restrictions: list[Restriction] = field(default_factory=list)

    @property
    def total_minor(self) -> int:
        return self.subtotal_minor + self.shipping_fee_minor + self.tax_minor


def _parse(timestamp: str | None) -> datetime | None:
    if not timestamp:
        return None
    text = timestamp.strip().replace("T", " ").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------- rules
def rule_organization_active(ctx: CreditContext) -> list[Restriction]:
    if ctx.organization_status == "active":
        return []
    return [Restriction(
        "organization_not_active",
        f"سازمان در وضعیت «{ctx.organization_status}» است و اعتبار آن قابل استفاده نیست.",
    )]


def rule_membership_active(ctx: CreditContext) -> list[Restriction]:
    if ctx.membership_status == "active":
        return []
    return [Restriction(
        "membership_inactive",
        "عضویت شما در این سازمان فعال نیست، بنابراین اعتبار سازمانی قابل استفاده نیست.",
    )]


def rule_allocation_status(ctx: CreditContext) -> list[Restriction]:
    if ctx.allocation_status == "active":
        return []
    return [Restriction(
        "allocation_not_active",
        f"این تخصیص اعتبار در وضعیت «{ctx.allocation_status}» است.",
    )]


def rule_validity_window(ctx: CreditContext) -> list[Restriction]:
    out: list[Restriction] = []
    starts = _parse(ctx.valid_from)
    ends = _parse(ctx.expires_at)
    if starts and ctx.now < starts:
        out.append(Restriction(
            "credit_not_started",
            f"این اعتبار از تاریخ {ctx.valid_from} قابل استفاده است.",
        ))
    if ends and ctx.now >= ends:
        out.append(Restriction(
            "credit_expired",
            f"اعتبار سازمانی در تاریخ {ctx.expires_at} منقضی شده است.",
        ))
    return out


def rule_sufficient_credit(ctx: CreditContext) -> list[Restriction]:
    if ctx.available_minor <= 0:
        return [Restriction("insufficient_credit", "اعتبار سازمانی در دسترس شما صفر است.")]
    return [Restriction(
        "available_credit_cap", "سقف اعتبار در دسترس", kind=CAP, cap_minor=ctx.available_minor,
    )]


def rule_per_transaction_limit(ctx: CreditContext) -> list[Restriction]:
    limit = ctx.per_transaction_limit_minor
    if limit is None:
        return []
    return [Restriction(
        "per_transaction_limit",
        f"سقف استفاده از اعتبار در هر خرید {limit} است.",
        kind=CAP, cap_minor=limit,
    )]


def rule_period_limit(ctx: CreditContext) -> list[Restriction]:
    limit = ctx.period_limit_minor
    if limit is None:
        return []
    remaining = max(0, limit - ctx.period_consumed_minor)
    if remaining == 0:
        return [Restriction("period_limit_reached", f"سقف دوره‌ای اعتبار ({limit}) مصرف شده است.")]
    return [Restriction(
        "period_limit",
        f"باقی‌مانده سقف دوره‌ای اعتبار: {remaining}",
        kind=CAP, cap_minor=remaining,
    )]


def rule_category_restriction(ctx: CreditContext) -> list[Restriction]:
    """Cap credit to the value of the lines whose category is permitted.

    Documented behaviour: when an allocation is category-restricted, the
    shipping fee is NOT credit-eligible; when it is unrestricted, it is. That
    keeps the quote explainable — the employee can point at exactly which
    lines their credit paid for.
    """
    allowed = ctx.category_slugs
    if not allowed:
        return []
    allowed_set = set(allowed)
    eligible = sum(l.line_total_minor for l in ctx.lines if l.category_slug in allowed_set)
    if eligible == 0:
        return [Restriction(
            "category_not_covered",
            "اعتبار سازمانی شما فقط برای دسته‌های "
            f"«{'، '.join(allowed)}» قابل استفاده است و هیچ کالای واجد شرایطی در سبد نیست.",
        )]
    return [Restriction(
        "category_restricted",
        "اعتبار سازمانی فقط برای دسته‌های "
        f"«{'، '.join(allowed)}» قابل استفاده است (هزینه ارسال مشمول نمی‌شود).",
        kind=CAP, cap_minor=eligible,
    )]


RULES: tuple[Callable[[CreditContext], list[Restriction]], ...] = (
    rule_organization_active,
    rule_membership_active,
    rule_allocation_status,
    rule_validity_window,
    rule_sufficient_credit,
    rule_per_transaction_limit,
    rule_period_limit,
    rule_category_restriction,
)


@dataclass(frozen=True)
class Evaluation:
    usable_minor: int
    blocked: bool
    restrictions: list[Restriction]

    @property
    def blocking(self) -> list[Restriction]:
        return [r for r in self.restrictions if r.kind == BLOCK]


def evaluate(ctx: CreditContext) -> Evaluation:
    """Run every rule and fold the caps into a single usable amount.

    A single BLOCK restriction takes credit off the table entirely. Otherwise
    the usable amount is the order total capped by every CAP restriction,
    floored at zero.
    """
    restrictions: list[Restriction] = []
    for rule in RULES:
        restrictions.extend(rule(ctx))

    blocking = [r for r in restrictions if r.kind == BLOCK]
    if blocking:
        return Evaluation(usable_minor=0, blocked=True, restrictions=restrictions)

    usable = ctx.total_minor
    for restriction in restrictions:
        if restriction.kind == CAP and restriction.cap_minor is not None:
            usable = min(usable, restriction.cap_minor)
    return Evaluation(usable_minor=max(0, usable), blocked=False, restrictions=restrictions)


def parse_category_slugs(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, list) and value else None
