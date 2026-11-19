"""Build policy items from the server's saved payment snapshot (never browser input)."""
from __future__ import annotations

from app.adapters.payment.base import GatewayError, PaymentRequest
from app.adapters.payment.sepehr import to_rial

SHIPPING_SKU = "__60online_shipping__"


def validate_category_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise ValueError("VANDAPAY_CATEGORY_MAP must be a non-empty JSON object")
    if any(not isinstance(k, str) or not k.strip() or k != k.strip()
           or not isinstance(v, str) or not v.strip() or v != v.strip() or len(v) > 100
           for k, v in value.items()):
        raise ValueError("VANDAPAY_CATEGORY_MAP must map exact slugs to category codes")
    return dict(value)


def _integer(value: object, field: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise GatewayError(f"vandapay basket: invalid {field}")
    return value


def _allocate(amount: int, weights: list[int]) -> list[int]:
    """Largest remainder, stable ties; integer arithmetic and exact sum."""
    total = sum(weights)
    if not total:
        if amount:
            raise GatewayError("vandapay basket: no taxable merchandise")
        return [0] * len(weights)
    shares = [amount * w // total for w in weights]
    order = sorted(range(len(weights)), key=lambda i: (-(amount * weights[i] % total), i))
    for i in order[:amount - sum(shares)]:
        shares[i] += 1
    return shares


def build_items(request: PaymentRequest, category_map: dict[str, str],
                shipping_category: str | None) -> list[dict]:
    basket = (request.metadata or {}).get("basket")
    if not isinstance(basket, dict):
        raise GatewayError("vandapay basket: saved snapshot required")
    # Local funding is not stored per line. Prorating its remainder could fund
    # an eligible line twice. Let VandaPay itself split credit/card in this pilot.
    if (_integer(basket.get("credit_minor"), "credit")
            or _integer(basket.get("welfare_minor"), "welfare")):
        raise GatewayError("vandapay basket: local funding needs per-item allocation")
    subtotal = _integer(basket.get("subtotal_minor"), "subtotal")
    tax = _integer(basket.get("tax_minor"), "tax")
    shipping = _integer(basket.get("shipping_fee_minor"), "shipping")
    total = _integer(basket.get("total_minor"), "total", 1)
    if subtotal + tax + shipping != total or total != request.amount_minor:
        raise GatewayError("vandapay basket: amount mismatch")
    lines = basket.get("items")
    if not isinstance(lines, list) or not lines:
        raise GatewayError("vandapay basket: items required")
    gross, normalized = [], []
    for line in lines:
        if not isinstance(line, dict):
            raise GatewayError("vandapay basket: invalid line")
        quantity = _integer(line.get("quantity"), "quantity", 1)
        unit = _integer(line.get("unit_price_minor"), "unit price")
        amount = _integer(line.get("line_total_minor"), "line total")
        sku = line.get("sku")
        if quantity > 10000 or unit * quantity != amount:
            raise GatewayError("vandapay basket: quantity/price mismatch")
        if not isinstance(sku, str) or not sku.strip() or len(sku) > 64 or sku == SHIPPING_SKU:
            raise GatewayError("vandapay basket: invalid or reserved SKU")
        slug = line.get("category_slug")
        category = category_map.get(slug) if isinstance(slug, str) else None
        if not category:
            raise GatewayError("vandapay basket: category has no approved mapping")
        normalized.append({"sku": sku, "quantity": quantity, "category": category,
                           "name": str(line.get("title_fa") or sku)[:200]})
        gross.append(amount)
    if subtotal > sum(gross):
        raise GatewayError("vandapay basket: subtotal exceeds merchandise")
    discounts = _allocate(sum(gross) - subtotal, gross)
    net = [amount - discount for amount, discount in zip(gross, discounts)]
    taxes = _allocate(tax, net)
    items = [{**line, "amount": to_rial(amount + line_tax, request.currency)}
             for line, amount, line_tax in zip(normalized, net, taxes) if amount + line_tax > 0]
    if shipping:
        if not shipping_category:
            raise GatewayError("vandapay basket: shipping category required")
        items.append({"sku": SHIPPING_SKU, "quantity": 1, "name": "هزینه ارسال",
                      "category": shipping_category, "amount": to_rial(shipping, request.currency)})
    if not 1 <= len(items) <= 50:
        raise GatewayError("vandapay basket: gateway accepts 1 to 50 payable lines")
    if sum(item["amount"] for item in items) != to_rial(total, request.currency):
        raise GatewayError("vandapay basket: allocated amount mismatch")
    return items
