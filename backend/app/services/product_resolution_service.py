"""Product Resolution Service — Phase 6 Final (Repaired).

Resolution pipeline:
1. Barcode/GTIN lookup in product_identifiers (confidence=10000 bps)
   → offer_id is THIS SUPPLIER's offer only (Blocker 2 fix)
2. Supplier SKU lookup in product_identifiers (confidence=9000 bps)
3. ERP code in erp_product_mappings where status='active' (confidence=9500 bps)
4. ProductKnowledgeSource lookup — enrich unknown product (Blocker 1 fix)
5. No match anywhere → NEW_CANONICAL (auto-create)
6. Multiple different product_ids → CONFLICT

Field provenance is persisted for knowledge-source enriched fields (Blocker 8 fix).

All money as INTEGER (Rials). No REAL/FLOAT anywhere.
"""
from __future__ import annotations

import datetime
import json
import sqlite3

from app.adapters.knowledge import registry as knowledge_registry


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _get_or_create_auto_category(conn: sqlite3.Connection) -> int:
    """Return id of the 'auto-discovered' category, creating it if needed."""
    row = conn.execute(
        "SELECT id FROM categories WHERE slug = 'auto-discovered'",
    ).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO categories (slug, name_fa, sort_order) VALUES (?, ?, ?)",
        ("auto-discovered", "کشف خودکار", 9999),
    )
    return int(cur.lastrowid)


def _get_first_supplier_location(conn: sqlite3.Connection, supplier_id: int) -> int | None:
    row = conn.execute(
        "SELECT id FROM supplier_locations WHERE supplier_id = ? AND status = 'active' LIMIT 1",
        (supplier_id,),
    ).fetchone()
    return int(row["id"]) if row else None


# ---------------------------------------------------------------------------
# Identifier lookups — BLOCKER 2 FIX: always return THIS SUPPLIER's offer
# ---------------------------------------------------------------------------

def _lookup_by_barcode(conn: sqlite3.Connection, barcode: str, supplier_id: int) -> list[dict]:
    """Return [{product_id, offer_id}] where offer_id is THIS SUPPLIER's active offer or None.

    Multiple product_ids for same barcode → CONFLICT detected by caller.
    BLOCKER 2: Never returns another supplier's offer_id.
    """
    pid_rows = conn.execute(
        """SELECT DISTINCT pi.product_id
           FROM product_identifiers pi
           WHERE pi.identifier_type = 'barcode' AND pi.identifier_value = ?""",
        (barcode,),
    ).fetchall()
    if not pid_rows:
        return []
    results = []
    for r in pid_rows:
        product_id = int(r["product_id"])
        # Find THIS supplier's offer only
        offer_row = conn.execute(
            """SELECT id FROM seller_offers
               WHERE product_id = ? AND supplier_id = ? AND status = 'active'
               LIMIT 1""",
            (product_id, supplier_id),
        ).fetchone()
        results.append({
            "product_id": product_id,
            "offer_id": int(offer_row["id"]) if offer_row else None,
        })
    return results


def _lookup_by_sku(conn: sqlite3.Connection, sku: str, supplier_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT pi.product_id, so.id AS offer_id
           FROM product_identifiers pi
           LEFT JOIN seller_offers so ON so.product_id = pi.product_id
               AND so.supplier_id = ? AND so.status = 'active'
           WHERE pi.identifier_type IN ('sku', 'supplier_sku')
             AND pi.identifier_value = ?
             AND (pi.supplier_id = ? OR pi.supplier_id IS NULL)
        """,
        (supplier_id, sku, supplier_id),
    ).fetchall()
    return [{"product_id": int(r["product_id"]), "offer_id": int(r["offer_id"]) if r["offer_id"] else None}
            for r in rows]


def _lookup_by_erp_code(conn: sqlite3.Connection, erp_code: str, connector_account_id: int, supplier_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT epm.product_id, so.id AS offer_id
           FROM erp_product_mappings epm
           LEFT JOIN seller_offers so ON so.product_id = epm.product_id
               AND so.supplier_id = ? AND so.status = 'active'
           WHERE epm.erp_product_code = ?
             AND epm.connector_account_id = ?
             AND epm.status = 'active'
        """,
        (supplier_id, erp_code, connector_account_id),
    ).fetchall()
    return [{"product_id": int(r["product_id"]), "offer_id": int(r["offer_id"]) if r["offer_id"] else None}
            for r in rows]


# ---------------------------------------------------------------------------
# Knowledge source lookup — BLOCKER 1 & 8 FIX
# ---------------------------------------------------------------------------

def _get_active_knowledge_sources(conn: sqlite3.Connection) -> list[str]:
    """Return adapter_keys of active knowledge sources, ordered by priority DESC.

    PRODUCTION SAFETY: Returns an empty list when no rows are configured.
    MockCatalogueKnowledgeSource is ONLY used when explicitly registered in
    knowledge_sources with is_active=1. It is NEVER injected as a silent fallback.
    """
    rows = conn.execute(
        "SELECT adapter_key FROM knowledge_sources WHERE is_active = 1 ORDER BY priority DESC"
    ).fetchall()
    return [r["adapter_key"] for r in rows]


def _query_knowledge_sources(
    conn: sqlite3.Connection,
    *,
    barcode: str | None,
    sku: str | None,
) -> tuple[dict | None, str | None]:
    """Query configured knowledge sources.

    Returns (enriched_data, adapter_key) or (None, None) if not found.
    """
    adapter_keys = _get_active_knowledge_sources(conn)
    for adapter_key in adapter_keys:
        try:
            source = knowledge_registry.get_knowledge_source(adapter_key)
        except Exception:
            continue
        enriched = None
        if barcode:
            enriched = source.lookup_by_identifier("barcode", barcode)
        if enriched is None and sku:
            enriched = source.lookup_by_identifier("sku", sku)
        if enriched is not None:
            return enriched, adapter_key
    return None, None


def _persist_field_provenance(
    conn: sqlite3.Connection,
    *,
    entity_type: str,
    entity_id: int,
    fields: dict,
    source_type: str,
    source_id: str,
    confidence_bps: int = 9000,
) -> None:
    """Persist field-level provenance for enriched fields. BLOCKER 8 FIX.

    Uses INSERT OR REPLACE so re-running is idempotent.
    """
    now = _now()
    for field_name, field_value in fields.items():
        if field_value is None:
            continue
        conn.execute(
            """INSERT OR REPLACE INTO field_provenance
               (entity_type, entity_id, field_name, field_value,
                source_type, source_id, external_ref, confidence_bps,
                retrieved_at, last_verified_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                entity_type, entity_id, field_name, str(field_value),
                source_type, source_id, None, confidence_bps,
                now, now,
            ),
        )


# ---------------------------------------------------------------------------
# Offer get-or-create (supplier-scoped)
# ---------------------------------------------------------------------------

def _get_or_create_offer(
    conn: sqlite3.Connection,
    *,
    product_id: int,
    supplier_id: int,
    sku: str,
    price_minor: int,
    stock: int,
) -> dict:
    """Find this supplier's offer or create a new one. Never touches another supplier's offer."""
    location_id = _get_first_supplier_location(conn, supplier_id)
    existing = conn.execute(
        """SELECT id FROM seller_offers
           WHERE product_id = ? AND supplier_id = ? AND status = 'active'
           LIMIT 1""",
        (product_id, supplier_id),
    ).fetchone()
    if existing:
        offer_id = int(existing["id"])
        # price/inventory are now updated via source model — just return the offer id
        return {"offer_id": offer_id, "created": False}
    else:
        gen_sku = sku or f"AUTO-{supplier_id}-{product_id}"
        cur = conn.execute(
            """INSERT INTO seller_offers
               (product_id, supplier_id, supplier_location_id, supplier_sku,
                selling_price_minor, cost_price_minor, stock_quantity, stock_reserved,
                status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            # cost_price_minor is NULL when unknown — NEVER fabricate from selling price
            (product_id, supplier_id, location_id, gen_sku,
             price_minor, None, stock, 0,
             "active", _now(), _now()),
        )
        return {"offer_id": int(cur.lastrowid), "created": True}


# ---------------------------------------------------------------------------
# Price / Inventory source model — BLOCKER 3 FIX
# ---------------------------------------------------------------------------

def _ensure_price_source(conn: sqlite3.Connection, *, connector_account_id: int, supplier_id: int) -> int:
    """Find or create a price_source for this connector account."""
    row = conn.execute(
        "SELECT id FROM price_sources WHERE connector_account_id = ? AND supplier_id = ? AND is_active = 1 LIMIT 1",
        (connector_account_id, supplier_id),
    ).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        """INSERT INTO price_sources
           (name, source_type, supplier_id, priority, connector_account_id, is_active, config_json)
           VALUES (?,?,?,?,?,?,?)""",
        (f"connector-{connector_account_id}", "connector", supplier_id, 10,
         connector_account_id, 1, "{}"),
    )
    return int(cur.lastrowid)


def _ensure_inventory_source(conn: sqlite3.Connection, *, connector_account_id: int, supplier_id: int) -> int:
    """Find or create an inventory_source for this connector account."""
    row = conn.execute(
        "SELECT id FROM inventory_sources WHERE connector_account_id = ? AND supplier_id = ? AND is_active = 1 LIMIT 1",
        (connector_account_id, supplier_id),
    ).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        """INSERT INTO inventory_sources
           (name, source_type, supplier_id, priority, connector_account_id, is_active, config_json)
           VALUES (?,?,?,?,?,?,?)""",
        (f"connector-{connector_account_id}", "connector", supplier_id, 10,
         connector_account_id, 1, "{}"),
    )
    return int(cur.lastrowid)


def _update_price_via_source_model(
    conn: sqlite3.Connection,
    *,
    offer_id: int,
    supplier_id: int,
    connector_account_id: int,
    price_minor: int,
    version: int,
) -> bool:
    """Write price through price_source → price_source_entries (with version protection).

    Returns True if price was updated (not stale), False if skipped.
    BLOCKER 3 FIX: price goes through source model, not directly to seller_offers.
    """
    if price_minor <= 0:
        return False
    price_source_id = _ensure_price_source(conn, connector_account_id=connector_account_id, supplier_id=supplier_id)
    now = _now()

    existing = conn.execute(
        "SELECT id, version FROM price_source_entries WHERE price_source_id = ? AND offer_id = ?",
        (price_source_id, offer_id),
    ).fetchone()

    # Only apply version staleness check when both sides have a real version
    if existing is not None and version is not None and int(existing["version"]) >= version:
        # Stale update — skip
        return False

    stored_version = version if version is not None else 0

    if existing is None:
        conn.execute(
            """INSERT INTO price_source_entries
               (price_source_id, offer_id, price_minor, currency, version, synced_at, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (price_source_id, offer_id, price_minor, "IRR", stored_version, now, now, now),
        )
    else:
        conn.execute(
            """UPDATE price_source_entries
               SET price_minor = ?, version = ?, synced_at = ?, updated_at = ?
               WHERE price_source_id = ? AND offer_id = ?""",
            (price_minor, stored_version, now, now, price_source_id, offer_id),
        )

    # Project authoritative price to seller_offers (highest-priority active source)
    auth_row = conn.execute(
        """SELECT pse.price_minor
           FROM price_source_entries pse
           JOIN price_sources ps ON ps.id = pse.price_source_id
           WHERE pse.offer_id = ? AND ps.is_active = 1
           ORDER BY ps.priority DESC LIMIT 1""",
        (offer_id,),
    ).fetchone()
    if auth_row:
        conn.execute(
            "UPDATE seller_offers SET selling_price_minor = ?, updated_at = ? WHERE id = ?",
            (int(auth_row["price_minor"]), now, offer_id),
        )
    return True


def _update_inventory_via_source_model(
    conn: sqlite3.Connection,
    *,
    offer_id: int,
    supplier_id: int,
    connector_account_id: int,
    stock: int,
    version: int,
) -> bool:
    """Write inventory through inventory_source → inventory_source_stock (with version protection).

    Returns True if stock was updated (not stale), False if skipped.
    BLOCKER 3 FIX: inventory goes through source model.
    """
    inventory_source_id = _ensure_inventory_source(conn, connector_account_id=connector_account_id, supplier_id=supplier_id)
    now = _now()

    existing = conn.execute(
        "SELECT id, version FROM inventory_source_stock WHERE inventory_source_id = ? AND offer_id = ?",
        (inventory_source_id, offer_id),
    ).fetchone()

    # Only apply version staleness check when both sides have a real version
    if existing is not None and version is not None and int(existing["version"]) >= version:
        return False

    stored_version = version if version is not None else 0

    if existing is None:
        conn.execute(
            """INSERT INTO inventory_source_stock
               (inventory_source_id, offer_id, quantity, version, synced_at, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (inventory_source_id, offer_id, stock, stored_version, now, now, now),
        )
    else:
        conn.execute(
            """UPDATE inventory_source_stock
               SET quantity = ?, version = ?, synced_at = ?, updated_at = ?
               WHERE inventory_source_id = ? AND offer_id = ?""",
            (stock, stored_version, now, now, inventory_source_id, offer_id),
        )

    # Project authoritative stock to seller_offers (highest-priority active source)
    auth_row = conn.execute(
        """SELECT iss.quantity
           FROM inventory_source_stock iss
           JOIN inventory_sources ins ON ins.id = iss.inventory_source_id
           WHERE iss.offer_id = ? AND ins.is_active = 1
           ORDER BY ins.priority DESC LIMIT 1""",
        (offer_id,),
    ).fetchone()
    if auth_row:
        conn.execute(
            "UPDATE seller_offers SET stock_quantity = ?, updated_at = ? WHERE id = ?",
            (int(auth_row["quantity"]), now, offer_id),
        )
    return True


# ---------------------------------------------------------------------------
# Canonical product creation
# ---------------------------------------------------------------------------

def _auto_create_canonical(
    conn: sqlite3.Connection,
    *,
    external: dict,
    supplier_id: int,
    connector_account_id: int,
    category_id: int,
    enriched: dict | None = None,
) -> dict:
    """Create canonical product + identifier + offer.

    enriched: data from knowledge source (optional, provides richer name/brand/category)
    Returns {"product_id": int, "offer_id": int, "was_created": bool}
    """
    erp_code = str(external.get("code") or external.get("erp_code") or "")
    barcode = external.get("barcode") or (enriched or {}).get("barcode") or ""
    sku = external.get("sku") or (enriched or {}).get("sku") or ""

    # Prefer enriched names/brands from knowledge source
    name_fa = (enriched or {}).get("name_fa") or external.get("name_fa") or external.get("name") or erp_code or "محصول ناشناس"
    brand_fa = (enriched or {}).get("brand_fa") or external.get("brand_fa") or external.get("brand") or "ناشناس"
    price_minor = int(external.get("price_minor") or 0)
    stock = int(external.get("stock_quantity") or external.get("stock") or 0)

    code_slug = erp_code.lower().replace(" ", "-").replace("_", "-")[:40]
    if barcode:
        slug = f"auto-bc-{barcode[:20]}"
    else:
        slug = f"auto-{supplier_id}-{code_slug}"
    gen_sku = sku or f"AUTO-{supplier_id}-{erp_code[:40]}"

    # Check if barcode already has a canonical product (idempotency)
    if barcode:
        existing_by_barcode = conn.execute(
            """SELECT pi.product_id FROM product_identifiers pi
               WHERE pi.identifier_type = 'barcode' AND pi.identifier_value = ?
               LIMIT 1""",
            (barcode,),
        ).fetchone()
        if existing_by_barcode:
            product_id = int(existing_by_barcode["product_id"])
            offer_result = _get_or_create_offer(
                conn, product_id=product_id, supplier_id=supplier_id,
                sku=gen_sku, price_minor=price_minor, stock=stock,
            )
            return {"product_id": product_id, "offer_id": offer_result["offer_id"], "was_created": False}

    # Check if slug already exists
    existing_prod = conn.execute(
        "SELECT id FROM products WHERE slug = ?", (slug,)
    ).fetchone()

    if existing_prod:
        product_id = int(existing_prod["id"])
        was_created = False
    else:
        cur = conn.execute(
            """INSERT INTO products
               (slug, sku, title_fa, description_fa, brand_fa, category_id,
                base_price_minor, currency, image_emoji, rating_x10, is_active,
                logistics_profile)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (slug, gen_sku, name_fa, f"کشف خودکار: {name_fa}", brand_fa,
             category_id, price_minor, "IRR", "📦", 0, 1, "standard"),
        )
        product_id = int(cur.lastrowid)
        was_created = True

    # Insert identifiers
    for id_type, id_val in [("barcode", barcode), ("sku", sku), ("erp_code", erp_code)]:
        if id_val:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO product_identifiers
                       (product_id, supplier_id, identifier_type, identifier_value, namespace, is_primary)
                       VALUES (?,?,?,?,?,?)""",
                    (product_id, supplier_id, id_type, id_val, "", 1 if id_type == "barcode" else 0),
                )
            except Exception:
                pass

    # Record erp_product_mapping
    if erp_code and connector_account_id:
        try:
            conn.execute(
                """INSERT OR REPLACE INTO erp_product_mappings
                   (connector_account_id, erp_product_code, product_id, supplier_id,
                    confidence_score_bps, match_method, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (connector_account_id, erp_code, product_id, supplier_id,
                 10000, "auto_created", "active", _now(), _now()),
            )
        except Exception:
            pass

    offer_result = _get_or_create_offer(
        conn, product_id=product_id, supplier_id=supplier_id,
        sku=gen_sku, price_minor=price_minor, stock=stock,
    )
    return {"product_id": product_id, "offer_id": offer_result["offer_id"], "was_created": was_created}


# ---------------------------------------------------------------------------
# Resolution attempt logging
# ---------------------------------------------------------------------------

def _record_resolution_attempt(
    conn: sqlite3.Connection,
    *,
    identifier_type: str,
    identifier_value: str,
    supplier_id: int,
    connector_account_id: int | None,
    sync_run_id: int | None,
    result: str,
    canonical_product_id: int | None,
    offer_id: int | None,
    confidence_bps: int,
    resolution_method: str,
    evidence: dict,
) -> int:
    cur = conn.execute(
        """INSERT INTO resolution_attempts
           (identifier_type, identifier_value, connector_account_id, supplier_id,
            sync_run_id, result, canonical_product_id, offer_id,
            confidence_bps, resolution_method, evidence_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            identifier_type, identifier_value,
            connector_account_id, supplier_id, sync_run_id,
            result, canonical_product_id, offer_id,
            confidence_bps, resolution_method,
            json.dumps(evidence, ensure_ascii=False),
        ),
    )
    return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Main resolution entry point
# ---------------------------------------------------------------------------

def resolve_product(
    conn: sqlite3.Connection,
    *,
    external: dict,
    connector_account_id: int,
    supplier_id: int,
    sync_run_id: int | None = None,
    knowledge_adapter_key: str | None = None,
) -> dict:
    """
    Resolve external product data to a canonical 60online product.

    Resolution priority:
    1. Barcode/GTIN → product_identifiers (confidence=10000 bps)
       Returns THIS SUPPLIER's offer_id only (B2 fix)
    2. Supplier SKU → product_identifiers (confidence=9000 bps)
    3. ERP code → erp_product_mappings (confidence=9500 bps)
    4. ProductKnowledgeSource → enrich + create canonical (B1 fix)
    5. No match → NEW_CANONICAL (auto-create without enrichment)
    6. Multiple different product_ids → CONFLICT

    For MATCHED: updates price/inventory via source model (B3 fix).
    For NEW_CANONICAL: writes provenance for enriched fields (B8 fix).

    Returns:
    {
      "result": "matched" | "new_canonical" | "ambiguous" | "conflict" | "rejected",
      "product_id": int | None,
      "offer_id": int | None,
      "confidence_bps": int,
      "resolution_method": str,
      "evidence": dict,
      "knowledge_adapter_used": str | None,
    }
    """
    barcode = external.get("barcode") or ""
    sku = external.get("sku") or ""
    erp_code = str(external.get("code") or external.get("erp_code") or "")
    price_minor = int(external.get("price_minor") or 0)
    stock = int(external.get("stock_quantity") or external.get("stock") or 0)
    # version = sync_run_id for out-of-order protection (B3)
    # None means "no version tracking" → always write through (no staleness check)
    version = sync_run_id  # may be None

    matches: list[dict] = []
    confidence_bps = 0
    resolution_method = "none"
    evidence: dict = {"barcode": barcode, "sku": sku, "erp_code": erp_code}

    # Step 1: Barcode lookup (BLOCKER 2 FIX: pass supplier_id)
    if barcode:
        hits = _lookup_by_barcode(conn, barcode, supplier_id)
        if hits:
            matches = hits
            confidence_bps = 10000
            resolution_method = "barcode_lookup"

    # Step 2: SKU lookup
    if not matches and sku:
        hits = _lookup_by_sku(conn, sku, supplier_id)
        if hits:
            matches = hits
            confidence_bps = 9000
            resolution_method = "sku_lookup"

    # Step 3: ERP code mapping
    if not matches and erp_code and connector_account_id:
        hits = _lookup_by_erp_code(conn, erp_code, connector_account_id, supplier_id)
        if hits:
            matches = hits
            confidence_bps = 9500
            resolution_method = "erp_mapping"

    if matches:
        # Check for conflict (multiple different product_ids)
        product_ids = list({m["product_id"] for m in matches})
        if len(product_ids) > 1:
            evidence["conflicting_product_ids"] = product_ids
            _record_resolution_attempt(
                conn,
                identifier_type="barcode" if barcode else ("sku" if sku else "erp_code"),
                identifier_value=barcode or sku or erp_code,
                supplier_id=supplier_id, connector_account_id=connector_account_id,
                sync_run_id=sync_run_id, result="conflict",
                canonical_product_id=None, offer_id=None, confidence_bps=0,
                resolution_method=resolution_method, evidence=evidence,
            )
            return {
                "result": "conflict", "product_id": None, "offer_id": None,
                "confidence_bps": 0, "resolution_method": resolution_method,
                "evidence": evidence, "knowledge_adapter_used": None,
            }

        product_id = product_ids[0]
        match = matches[0]
        offer_id = match["offer_id"]

        # If no offer for this supplier yet → create one (BLOCKER 2 FIX)
        if offer_id is None:
            gen_sku = sku or erp_code or f"AUTO-{supplier_id}-{product_id}"
            offer_result = _get_or_create_offer(
                conn, product_id=product_id, supplier_id=supplier_id,
                sku=gen_sku, price_minor=price_minor, stock=stock,
            )
            offer_id = offer_result["offer_id"]

        # Update price/inventory via source model (BLOCKER 3 FIX)
        if connector_account_id:
            _update_price_via_source_model(
                conn, offer_id=offer_id, supplier_id=supplier_id,
                connector_account_id=connector_account_id,
                price_minor=price_minor, version=version,
            )
            _update_inventory_via_source_model(
                conn, offer_id=offer_id, supplier_id=supplier_id,
                connector_account_id=connector_account_id,
                stock=stock, version=version,
            )

        _record_resolution_attempt(
            conn,
            identifier_type="barcode" if barcode else ("sku" if sku else "erp_code"),
            identifier_value=barcode or sku or erp_code,
            supplier_id=supplier_id, connector_account_id=connector_account_id,
            sync_run_id=sync_run_id, result="matched",
            canonical_product_id=product_id, offer_id=offer_id,
            confidence_bps=confidence_bps, resolution_method=resolution_method,
            evidence=evidence,
        )
        return {
            "result": "matched", "product_id": product_id, "offer_id": offer_id,
            "confidence_bps": confidence_bps, "resolution_method": resolution_method,
            "evidence": evidence, "knowledge_adapter_used": None,
        }

    # Step 4: Query ProductKnowledgeSources (BLOCKER 1 FIX)
    enriched, adapter_key_used = _query_knowledge_sources(conn, barcode=barcode, sku=sku)
    knowledge_confidence = int((enriched or {}).get("confidence_bps", 9000)) if enriched else 0

    # Step 5: Create canonical product (with or without enrichment)
    category_id = _get_or_create_auto_category(conn)

    if enriched:
        resolution_method = f"knowledge_enriched:{adapter_key_used}"
        evidence["knowledge_adapter"] = adapter_key_used
        evidence["enriched_fields"] = list(enriched.keys())

    created = _auto_create_canonical(
        conn, external=external, supplier_id=supplier_id,
        connector_account_id=connector_account_id,
        category_id=category_id, enriched=enriched,
    )
    product_id = created["product_id"]
    offer_id = created["offer_id"]

    # Persist field provenance for knowledge-enriched fields (BLOCKER 8 FIX)
    if enriched and adapter_key_used:
        provenance_fields = {
            k: v for k, v in enriched.items()
            if k in ("name_fa", "brand_fa", "category_hint", "barcode", "sku", "price_minor")
        }
        _persist_field_provenance(
            conn, entity_type="product", entity_id=product_id,
            fields=provenance_fields,
            source_type="knowledge_source", source_id=adapter_key_used,
            confidence_bps=knowledge_confidence,
        )

    # Write price/inventory via source model (BLOCKER 3 FIX)
    if connector_account_id and offer_id:
        _update_price_via_source_model(
            conn, offer_id=offer_id, supplier_id=supplier_id,
            connector_account_id=connector_account_id,
            price_minor=price_minor, version=version,
        )
        _update_inventory_via_source_model(
            conn, offer_id=offer_id, supplier_id=supplier_id,
            connector_account_id=connector_account_id,
            stock=stock, version=version,
        )

    result_type = "new_canonical"
    _record_resolution_attempt(
        conn,
        identifier_type="barcode" if barcode else ("sku" if sku else "erp_code"),
        identifier_value=barcode or sku or erp_code,
        supplier_id=supplier_id, connector_account_id=connector_account_id,
        sync_run_id=sync_run_id, result=result_type,
        canonical_product_id=product_id, offer_id=offer_id,
        confidence_bps=knowledge_confidence if enriched else 5000,
        resolution_method=resolution_method,
        evidence={**evidence, "created_product_id": product_id, "created_offer_id": offer_id},
    )
    return {
        "result": result_type, "product_id": product_id, "offer_id": offer_id,
        "confidence_bps": knowledge_confidence if enriched else 5000,
        "resolution_method": resolution_method,
        "evidence": evidence, "knowledge_adapter_used": adapter_key_used,
    }
