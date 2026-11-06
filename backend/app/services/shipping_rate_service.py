"""Phase 5C — carrier rate shopping.

quote_shipping(conn, origin, destination, parcels) prices every enabled carrier
(Tipax, Chapar, Post/پست پیشتاز, Alopeyk for same-city) per service level.
A carrier with a live API is asked through an injectable ``live_quoter``
(no network in tests); otherwise — or if the live call fails — the local
rule-based tariff is used: base + per-kg × billable weight (max of actual and
volumetric, rounded up to the tariff weight step) with a province zone matrix,
remote-area / fragile surcharges, COD fee and insurance. Integer Rial only.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Callable

from app.core.errors import NotFoundError, ValidationError
from app.services import product_standards_service as pss

SERVICE_LEVELS = ("same_day", "express", "economy")
STRATEGIES = ("cheapest", "fastest")

LiveQuoter = Callable[[str, dict], list]


def _norm(s) -> str:
    return " ".join(str(s or "").replace("ي", "ی").replace("ك", "ک").split())


def _place(p: dict, label: str) -> dict:
    if not isinstance(p, dict) or not _norm(p.get("province")) or not _norm(p.get("city")):
        raise ValidationError(f"استان و شهر {label} الزامی است", code="invalid_address")
    return {"province": _norm(p["province"]), "city": _norm(p["city"])}


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def resolve_parcels(conn: sqlite3.Connection, parcels: list) -> list[dict]:
    """Each parcel: explicit dims/weight, or {product_id[, seller_offer_id], quantity} from specs."""
    if not isinstance(parcels, list) or not parcels:
        raise ValidationError("حداقل یک بسته برای استعلام لازم است", code="no_parcels")
    out = []
    for p in parcels:
        if not isinstance(p, dict):
            raise ValidationError("بسته نامعتبر است", code="invalid_parcel")
        qty = p.get("quantity", 1)
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise ValidationError("تعداد بسته نامعتبر است", code="invalid_quantity")
        if p.get("product_id") is not None:
            spec = pss.get_spec(conn, product_id=int(p["product_id"]),
                                seller_offer_id=p.get("seller_offer_id"))
            if spec is None:
                raise ValidationError("ابعاد و وزن بسته‌بندی این کالا ثبت نشده است",
                                      code="logistics_spec_missing")
            base = {k: spec[k] for k in ("length_mm", "width_mm", "height_mm", "gross_weight_g",
                                         "is_fragile", "requires_cold_chain", "hazmat_class")}
        else:
            n = pss.normalize_spec({**p, "gross_weight_g": p.get("gross_weight_g", p.get("weight_g"))})
            base = {k: n[k] for k in ("length_mm", "width_mm", "height_mm", "gross_weight_g",
                                      "is_fragile", "requires_cold_chain", "hazmat_class")}
        out.extend(dict(base) for _ in range(qty))
    return out


def _zone(conn, tariff_id: int, o: str, d: str):
    cands = [(o, d), (o, "*"), ("*", d)] + ([("*", "=")] if o == d else []) + [("*", "*")]
    for a, b in cands:
        row = conn.execute(
            "SELECT * FROM carrier_tariff_zones WHERE tariff_id=? AND origin_province=? AND destination_province=?",
            (tariff_id, a, b),
        ).fetchone()
        if row:
            return row
    return None


def _is_remote(conn, place: dict) -> bool:
    return conn.execute(
        "SELECT 1 FROM logistics_remote_areas WHERE province=? AND city IN (?, '*')",
        (place["province"], place["city"]),
    ).fetchone() is not None


def price_tariff(conn, tariff, origin: dict, destination: dict, parcels: list[dict], *,
                 cod_value_minor: int = 0, insurance_value_minor: int = 0) -> dict | None:
    """Rule-based price for one tariff. Returns None if the tariff cannot carry it."""
    t = dict(tariff)
    divisor = int(t["volumetric_divisor"])
    actual = sum(p["gross_weight_g"] for p in parcels)
    vol = sum(pss.volumetric_weight_g(p["length_mm"], p["width_mm"], p["height_mm"], divisor) for p in parcels)
    billable_raw = sum(max(p["gross_weight_g"],
                           pss.volumetric_weight_g(p["length_mm"], p["width_mm"], p["height_mm"], divisor))
                       for p in parcels)
    step = int(t["weight_step_g"])
    billable = _ceil_div(billable_raw, step) * step
    if t["max_weight_g"] is not None and billable > int(t["max_weight_g"]):
        return None
    z = _zone(conn, t["id"], origin["province"], destination["province"])
    base = int(z["base_minor"]) if z is not None and z["base_minor"] is not None else int(t["base_minor"])
    per_kg = int(z["per_kg_minor"]) if z is not None and z["per_kg_minor"] is not None else int(t["per_kg_minor"])
    eta_min = int(z["transit_days_min"]) if z is not None and z["transit_days_min"] is not None else int(t["transit_days_min"])
    eta_max = int(z["transit_days_max"]) if z is not None and z["transit_days_max"] is not None else int(t["transit_days_max"])
    eta_max = max(eta_min, eta_max)
    weight_charge = per_kg * billable // 1000
    remote = int(t["remote_surcharge_minor"]) if _is_remote(conn, destination) else 0
    fragile = int(t["fragile_surcharge_minor"]) if any(p["is_fragile"] for p in parcels) else 0
    cod_fee = 0
    if cod_value_minor > 0:
        if not t["supports_cod"]:
            return None
        cod_fee = max(int(t["cod_min_fee_minor"]), cod_value_minor * int(t["cod_fee_bps"]) // 10000)
    insurance = insurance_value_minor * int(t["insurance_bps"]) // 10000
    cost = base + weight_charge + remote + fragile + cod_fee + insurance
    price = cost + cost * int(t["markup_bps"]) // 10000
    return {
        "provider_code": t["provider_code"], "tariff_id": t["id"], "service_level": t["service_level"],
        "service_name_fa": t["name_fa"], "source": "tariff",
        "actual_weight_g": actual, "volumetric_weight_g": vol, "billable_weight_g": billable,
        "cost_minor": cost, "price_minor": price, "eta_days_min": eta_min, "eta_days_max": eta_max,
        "breakdown": {"base_minor": base, "weight_minor": weight_charge, "remote_minor": remote,
                      "fragile_minor": fragile, "cod_fee_minor": cod_fee, "insurance_minor": insurance},
    }


def _carrier_ok(carrier, origin: dict, destination: dict, parcels: list[dict]) -> bool:
    caps = {c.strip() for c in (carrier["capabilities"] or "").split(",") if c.strip()}
    same_city = origin["province"] == destination["province"] and origin["city"] == destination["city"]
    if carrier["same_city_only"] and not same_city:
        return False
    if any(p["requires_cold_chain"] for p in parcels) and "cold_chain" not in caps:
        return False
    if any(p["hazmat_class"] for p in parcels) and "hazmat" not in caps:
        return False
    return True


def quote_shipping(conn: sqlite3.Connection, origin: dict, destination: dict, parcels: list, *,
                   cod_value_minor: int = 0, insurance_value_minor: int = 0,
                   service_levels: list | None = None, strategy: str = "cheapest",
                   live_quoter: LiveQuoter | None = None, persist: bool = False,
                   fulfillment_order_id: int | None = None) -> dict:
    """Quote every enabled carrier; return options sorted by strategy plus the chosen one."""
    origin, destination = _place(origin, "مبدأ"), _place(destination, "مقصد")
    if strategy not in STRATEGIES:
        raise ValidationError("راهبرد انتخاب باید cheapest یا fastest باشد", code="invalid_strategy")
    for v in (cod_value_minor, insurance_value_minor):
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ValidationError("مبلغ پرداخت در محل یا ارزش بیمه نامعتبر است", code="invalid_amount")
    levels = set(service_levels or SERVICE_LEVELS)
    if not levels <= set(SERVICE_LEVELS):
        raise ValidationError("سطح خدمت ارسال نامعتبر است", code="invalid_service_level")
    resolved = resolve_parcels(conn, parcels)
    same_city = origin["province"] == destination["province"] and origin["city"] == destination["city"]
    if not same_city:
        levels.discard("same_day")

    options: list[dict] = []
    for carrier in conn.execute("SELECT * FROM logistics_carriers WHERE is_enabled=1 ORDER BY provider_code"):
        if not _carrier_ok(carrier, origin, destination, resolved):
            continue
        tariffs = [t for t in conn.execute(
            "SELECT * FROM carrier_tariffs WHERE provider_code=? AND is_active=1 ORDER BY id",
            (carrier["provider_code"],)) if t["service_level"] in levels]
        live: list[dict] = []
        if carrier["has_live_api"] and live_quoter is not None:
            try:
                req = {"origin": origin, "destination": destination, "parcels": resolved,
                       "cod_value_minor": cod_value_minor, "insurance_value_minor": insurance_value_minor}
                for q in live_quoter(carrier["provider_code"], req) or []:
                    if q.get("service_level") in levels and isinstance(q.get("cost_minor"), int):
                        tmpl = next((price_tariff(conn, t, origin, destination, resolved,
                                                  cod_value_minor=cod_value_minor,
                                                  insurance_value_minor=insurance_value_minor)
                                     for t in tariffs if t["service_level"] == q["service_level"]), None)
                        weights = tmpl or {"actual_weight_g": sum(p["gross_weight_g"] for p in resolved),
                                           "volumetric_weight_g": 0, "billable_weight_g": 0}
                        live.append({
                            "provider_code": carrier["provider_code"], "tariff_id": None,
                            "service_level": q["service_level"], "service_name_fa": carrier["name_fa"],
                            "source": "live", "actual_weight_g": weights["actual_weight_g"],
                            "volumetric_weight_g": weights["volumetric_weight_g"],
                            "billable_weight_g": weights["billable_weight_g"],
                            "cost_minor": int(q["cost_minor"]),
                            "price_minor": int(q.get("price_minor", q["cost_minor"])),
                            "eta_days_min": int(q.get("eta_days_min", 1)),
                            "eta_days_max": int(q.get("eta_days_max", q.get("eta_days_min", 1))),
                            "breakdown": {"live": True},
                        })
            except Exception:  # live API down → fall back to local tariff
                live = []
        if live:
            options.extend(live)
            continue
        for t in tariffs:
            q = price_tariff(conn, t, origin, destination, resolved,
                             cod_value_minor=cod_value_minor, insurance_value_minor=insurance_value_minor)
            if q:
                options.append(q)
    if not options:
        raise NotFoundError("هیچ شرکت حمل فعالی برای این مسیر و بسته در دسترس نیست",
                            code="no_carrier_available")
    if strategy == "cheapest":
        options.sort(key=lambda o: (o["price_minor"], o["eta_days_max"], o["provider_code"]))
    else:
        options.sort(key=lambda o: (o["eta_days_max"], o["price_minor"], o["provider_code"]))
    group = uuid.uuid4().hex
    for o in options:
        o.update(cod=1 if cod_value_minor else 0, insurance_value_minor=insurance_value_minor)
    if persist:
        for i, o in enumerate(options):
            cur = conn.execute(
                "INSERT INTO shipping_quotes (quote_group, fulfillment_order_id, provider_code, tariff_id, "
                "service_level, source, origin_province, origin_city, destination_province, destination_city, "
                "actual_weight_g, volumetric_weight_g, billable_weight_g, cost_minor, price_minor, cod, "
                "insurance_value_minor, eta_days_min, eta_days_max, breakdown_json, is_selected) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (group, fulfillment_order_id, o["provider_code"], o["tariff_id"], o["service_level"],
                 o["source"], origin["province"], origin["city"], destination["province"],
                 destination["city"], o["actual_weight_g"], o["volumetric_weight_g"],
                 o["billable_weight_g"], o["cost_minor"], o["price_minor"], o["cod"],
                 insurance_value_minor, o["eta_days_min"], o["eta_days_max"],
                 json.dumps(o["breakdown"]), 1 if i == 0 else 0),
            )
            o["quote_id"] = int(cur.lastrowid)
    return {"quote_group": group, "strategy": strategy, "selected": options[0], "options": options}


def public_option(o: dict) -> dict:
    """Buyer-facing view: never exposes internal carrier cost or tariff breakdown."""
    keys = ("quote_id", "provider_code", "service_level", "service_name_fa", "price_minor",
            "eta_days_min", "eta_days_max", "billable_weight_g", "cod")
    return {k: o[k] for k in keys if k in o}


def persist_selected_quote_on_plan(conn: sqlite3.Connection, fulfillment_order_id: int, quote_id: int) -> None:
    """Persist the chosen quote on the phase-5 shipment plan (creating the plan if absent)."""
    q = conn.execute("SELECT * FROM shipping_quotes WHERE id=?", (quote_id,)).fetchone()
    if q is None:
        raise NotFoundError("استعلام ارسال یافت نشد", code="quote_not_found")
    conn.execute("UPDATE shipping_quotes SET is_selected = CASE WHEN id=? THEN 1 ELSE 0 END "
                 "WHERE quote_group=?", (quote_id, q["quote_group"]))
    if conn.execute("SELECT 1 FROM shipment_plans WHERE fulfillment_order_id=?",
                    (fulfillment_order_id,)).fetchone():
        conn.execute(
            "UPDATE shipment_plans SET selected_quote_id=?, selected_quote_price_minor=?, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE fulfillment_order_id=?",
            (quote_id, q["price_minor"], fulfillment_order_id),
        )
    else:
        conn.execute(
            "INSERT INTO shipment_plans (fulfillment_order_id, status, selected_quote_id, "
            "selected_quote_price_minor) VALUES (?, 'quote_selected', ?, ?)",
            (fulfillment_order_id, quote_id, q["price_minor"]),
        )


# ----------------------------------------------------------------- admin tariff CRUD
_TARIFF_INT = ("base_minor", "per_kg_minor", "weight_step_g", "volumetric_divisor", "max_weight_g",
               "remote_surcharge_minor", "fragile_surcharge_minor", "cod_fee_bps", "cod_min_fee_minor",
               "insurance_bps", "markup_bps", "supports_cod", "transit_days_min", "transit_days_max",
               "is_active")


def _tariff_values(data: dict, partial: bool) -> dict:
    vals = {}
    if not partial or "provider_code" in data:
        vals["provider_code"] = str(data.get("provider_code") or "").strip()
    if not partial or "service_level" in data:
        if data.get("service_level") not in SERVICE_LEVELS:
            raise ValidationError("سطح خدمت ارسال نامعتبر است", code="invalid_service_level")
        vals["service_level"] = data["service_level"]
    if not partial or "name_fa" in data:
        if not str(data.get("name_fa") or "").strip():
            raise ValidationError("نام تعرفه الزامی است", code="name_required")
        vals["name_fa"] = str(data["name_fa"]).strip()
    for k in _TARIFF_INT:
        if k in data:
            v = data[k]
            if k == "max_weight_g" and v is None:
                vals[k] = None
                continue
            if isinstance(v, bool):
                v = int(v)
            if not isinstance(v, int) or v < 0:
                raise ValidationError(f"مقدار «{k}» باید عدد صحیح نامنفی باشد", code="invalid_tariff_value")
            vals[k] = v
    for k in ("weight_step_g", "volumetric_divisor"):
        if k in vals and vals[k] <= 0:
            raise ValidationError(f"مقدار «{k}» باید مثبت باشد", code="invalid_tariff_value")
    return vals


def _save_zones(conn, tariff_id: int, zones) -> None:
    if zones is None:
        return
    if not isinstance(zones, list):
        raise ValidationError("ماتریس مناطق نامعتبر است", code="invalid_zones")
    conn.execute("DELETE FROM carrier_tariff_zones WHERE tariff_id=?", (tariff_id,))
    for z in zones:
        o, d = _norm(z.get("origin_province")), _norm(z.get("destination_province"))
        if not o or not d:
            raise ValidationError("استان مبدأ و مقصد در ماتریس مناطق الزامی است", code="invalid_zones")
        conn.execute(
            "INSERT INTO carrier_tariff_zones (tariff_id, origin_province, destination_province, base_minor, "
            "per_kg_minor, transit_days_min, transit_days_max) VALUES (?,?,?,?,?,?,?)",
            (tariff_id, o, d, z.get("base_minor"), z.get("per_kg_minor"),
             z.get("transit_days_min"), z.get("transit_days_max")),
        )


def get_tariff(conn, tariff_id: int) -> dict:
    row = conn.execute("SELECT * FROM carrier_tariffs WHERE id=?", (tariff_id,)).fetchone()
    if row is None:
        raise NotFoundError("تعرفه یافت نشد", code="tariff_not_found")
    d = dict(row)
    d["zones"] = [dict(z) for z in conn.execute(
        "SELECT origin_province, destination_province, base_minor, per_kg_minor, transit_days_min, "
        "transit_days_max FROM carrier_tariff_zones WHERE tariff_id=? ORDER BY id", (tariff_id,))]
    return d


def list_tariffs(conn) -> list[dict]:
    return [get_tariff(conn, r["id"]) for r in conn.execute("SELECT id FROM carrier_tariffs ORDER BY id")]


def create_tariff(conn, data: dict) -> dict:
    vals = _tariff_values(data, partial=False)
    if conn.execute("SELECT 1 FROM logistics_carriers WHERE provider_code=?",
                    (vals["provider_code"],)).fetchone() is None:
        raise ValidationError("شرکت حمل ناشناخته است", code="unknown_carrier")
    cols = list(vals)
    cur = conn.execute(f"INSERT INTO carrier_tariffs ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                       [vals[c] for c in cols])
    tid = int(cur.lastrowid)
    _save_zones(conn, tid, data.get("zones"))
    return get_tariff(conn, tid)


def update_tariff(conn, tariff_id: int, data: dict) -> dict:
    current = get_tariff(conn, tariff_id)
    vals = _tariff_values(data, partial=True)
    vals.pop("provider_code", None)
    merged = {**current, **vals}
    if merged["transit_days_max"] < merged["transit_days_min"]:
        raise ValidationError("حداکثر زمان ترانزیت نباید کمتر از حداقل باشد", code="invalid_tariff_value")
    if vals:
        conn.execute("UPDATE carrier_tariffs SET " + ", ".join(f"{c}=?" for c in vals)
                     + ", updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                     [*vals.values(), tariff_id])
    t = get_tariff(conn, tariff_id)
    if t["transit_days_max"] < t["transit_days_min"]:
        raise ValidationError("حداکثر زمان ترانزیت نباید کمتر از حداقل باشد", code="invalid_tariff_value")
    _save_zones(conn, tariff_id, data.get("zones"))
    return get_tariff(conn, tariff_id)


def deactivate_tariff(conn, tariff_id: int) -> dict:
    get_tariff(conn, tariff_id)
    conn.execute("UPDATE carrier_tariffs SET is_active=0, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                 "WHERE id=?", (tariff_id,))
    return get_tariff(conn, tariff_id)
