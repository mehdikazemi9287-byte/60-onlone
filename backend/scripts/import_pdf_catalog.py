"""Plan/apply provenance-preserving PDF rows to the existing SQLite catalog.

No schema creation, inferred stock, sale offers, or existing-master updates.
Unknown required attributes are retained in external_product_mappings.
Apply requires an exact reviewed plan digest and a new private journal.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sqlite3
import uuid
from collections import defaultdict
from pathlib import Path


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def digest(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def identity(row):
    if row.get("supplier_product_code"):
        return row["supplier"] + ":sku:" + row["supplier_product_code"]
    return row["supplier"] + ":identity:" + digest([
        row["normalized_name"], row.get("brand"), row.get("variant"),
        row.get("weight"), row.get("weight_unit"), row.get("size"), row.get("packaging")])


def plan(conn, rows, reviewed_source_changes=None):
    reviewed_source_changes = reviewed_source_changes or {}
    groups = defaultdict(list)
    for row in rows:
        groups[identity(row)].append(row)
    result = []
    for key, sources in sorted(groups.items()):
        # Explicit newer consumer-list rows take precedence for identity labels;
        # every older catalog value remains in the provenance record.
        sources = sorted(sources, key=lambda r: (r.get("price_type") == "consumer", r.get("source_date") or ""), reverse=True)
        representative = sources[0]
        existing = conn.execute(
            "SELECT id,master_product_id,status,external_metadata_json FROM external_product_mappings "
            "WHERE external_identifier_type='PDF_CATALOG' AND external_identifier_value=?", (key,)
        ).fetchall()
        if len(existing) > 1:
            raise ValueError("Duplicate existing mapping: " + key)
        pending_mapping_id = None
        if existing:
            source_changed = json.loads(existing[0]["external_metadata_json"]) != {"identity": key, "sources": sources}
            if source_changed:
                if reviewed_source_changes.get(key) != digest(json.loads(existing[0]["external_metadata_json"])):
                    raise ValueError("Previously staged source changed; review required: " + key)
                if existing[0]["master_product_id"] is not None:
                    result.append({"identity": key, "supplier": representative["supplier"], "action": "source_update", "master_id": existing[0]["master_product_id"], "sources": sources, "pending_mapping_id": existing[0]["id"]})
                    continue
            if existing[0]["master_product_id"] is not None or existing[0]["status"] != "pending_review" or any(r.get("issues") for r in sources):
                result.append({"identity": key, "supplier": representative["supplier"], "action": "skip",
                               "master_id": existing[0]["master_product_id"], "sources": sources})
                continue
            pending_mapping_id = existing[0]["id"]
        matches = []
        sku = representative.get("supplier_product_code")
        if sku:
            matches = conn.execute(
                "SELECT DISTINCT master_product_id FROM product_identifiers_legacy "
                "WHERE identifier_type='SUPPLIER_SKU' AND identifier_value=? AND issuer=? AND is_active=1",
                (sku, representative["supplier"]),
            ).fetchall()
        if not matches:
            matches = conn.execute(
                "SELECT id AS master_product_id FROM master_products WHERE status!='merged' "
                "AND canonical_name_fa=? AND COALESCE(brand,'')=? AND COALESCE(variant,'')=? "
                "AND COALESCE(size_label,'')=? AND COALESCE(net_quantity,'')=?",
                (representative["normalized_name"], representative.get("brand") or "",
                 representative.get("variant") or "", representative.get("size") or "",
                 (str(representative["weight"]) + representative["weight_unit"]) if representative.get("weight") else ""),
            ).fetchall()
            # Different declared supplier codes remain distinct variants.
            matches = [m for m in matches if not sku or not conn.execute(
                "SELECT 1 FROM product_identifiers_legacy WHERE master_product_id=? AND identifier_type='SUPPLIER_SKU' AND issuer=? AND identifier_value!=?",
                (m["master_product_id"], representative["supplier"], sku)).fetchone()]
        issues = sorted({issue for source in sources for issue in source.get("issues", [])})
        if len(matches) > 1:
            issues.append("ambiguous_existing_identity")
        if sku and not matches:
            collision = conn.execute("SELECT 1 FROM product_identifiers_legacy WHERE identifier_type='SUPPLIER_SKU' AND identifier_value=? AND supplier_id IS NULL AND organization_id IS NULL", (sku,)).fetchone()
            if collision:
                issues.append("unscoped_supplier_identifier_collision")
        if not representative.get("normalized_name"):
            issues.append("empty_name")
        action = "review" if issues else ("match" if matches else "create")
        result.append({"identity": key, "supplier": representative["supplier"], "action": action,
                       "master_id": matches[0]["master_product_id"] if len(matches) == 1 else None,
                       "issues": sorted(set(issues)), "sources": sources, "pending_mapping_id": pending_mapping_id})
    return result


def insert(conn, table, values):
    cols = list(values)
    return conn.execute("INSERT INTO " + table + " (" + ",".join(cols) + ") VALUES (" + ",".join("?" for _ in cols) + ")", [values[c] for c in cols]).lastrowid


def apply(conn, operations):
    journal = []
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for op in operations:
        if op["action"] == "skip":
            continue
        row = op["sources"][0]
        mid = op["master_id"]
        metadata = {"identity": op["identity"], "sources": op["sources"]}
        if op["action"] == "create":
            if not conn.execute("SELECT 1 FROM categories WHERE slug=?", (row["category"],)).fetchone():
                raise ValueError("Unknown existing category: " + row["category"])
            values = {
                "public_product_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "60online:pdf:" + op["identity"])),
                "canonical_name_fa": row["normalized_name"], "brand": row.get("brand"),
                "category": row["category"], "subcategory": row.get("subcategory"),
                "variant": row.get("variant"), "size_label": row.get("size"),
                "unit": row["unit"], "package_quantity": row["carton_quantity"],
                "net_quantity": (str(row["weight"]) + row["weight_unit"]) if row.get("weight") else None,
                "description_fa": row.get("description"), "image_urls_json": dumps(row.get("images", [])),
                "specifications_json": dumps({"pdf_catalog": metadata, "package_quantity_basis": "source_declared_carton_quantity", "source_unit": row["unit"], "retail_pack_quantity": row.get("pack_qty"), "stock": None, "prices_are_not_sale_offers": True}),
                "status": "active", "created_at": now, "updated_at": now,
            }
            mid = insert(conn, "master_products", values)
            journal.append({"table": "master_products", "key": mid, "after": {"id": mid, **values}})
            sku = row.get("supplier_product_code")
            if sku:
                values = {"master_product_id": mid, "identifier_type": "SUPPLIER_SKU", "identifier_value": sku,
                          "issuer": row["supplier"], "supplier_id": None, "metadata_json": dumps({"supplier_identity_unverified": True, "source_identity": op["identity"]})}
                ident = insert(conn, "product_identifiers_legacy", values)
                journal.append({"table": "product_identifiers_legacy", "key": ident, "after": {"id": ident, **values}})
            values = {"master_product_id": mid, "slug": "pdf-" + digest(op["identity"])[:20],
                      "category_slug": row["category"], "verified_price_minor": None,
                      "currency": "IRR", "is_visible": 1, "is_purchasable": 0,
                      "price_status": "pending", "publication_reason": "pdf_catalog_inquiry_only; source currency remains in provenance",
                      "created_at": now, "updated_at": now}
            insert(conn, "catalog_publications", values)
            journal.append({"table": "catalog_publications", "key": mid, "after": values})
        values = {"external_identifier_type": "PDF_CATALOG", "external_identifier_value": op["identity"],
                  "external_description": row["original_name"], "external_metadata_json": dumps(metadata),
                  "supplier_id": None, "master_product_id": mid,
                  "status": "pending_review" if op["action"] == "review" else ("mapped" if op["action"] in ("match", "source_update") else "new_product_created"),
                  "notes": dumps({"issues": op.get("issues", []), "supplier": row["supplier"], "supplier_account": "not_created_without_verified_national_id", "sale_offer": "not_created_without_verified_price_currency_and_stock"}),
                  "created_at": now, "updated_at": now}
        if op.get("pending_mapping_id"):
            mapping = op["pending_mapping_id"]
            before = dict(conn.execute("SELECT * FROM external_product_mappings WHERE id=?", (mapping,)).fetchone())
            conn.execute("UPDATE external_product_mappings SET master_product_id=?,status=?,external_metadata_json=?,notes=?,updated_at=? WHERE id=?", (mid, values["status"], values["external_metadata_json"], values["notes"], now, mapping))
            journal.append({"table": "external_product_mappings", "key": mapping, "before": before, "after": dict(conn.execute("SELECT * FROM external_product_mappings WHERE id=?", (mapping,)).fetchone())})
        else:
            mapping = insert(conn, "external_product_mappings", values)
            journal.append({"table": "external_product_mappings", "key": mapping, "after": {"id": mapping, **values}})
    return journal


def hide_imported_publications(conn, journal):
    """Reversible visibility rollback; preserves source records and master IDs.

    Refuse independent edits. This does not delete or replace any database.
    """
    publications = [r for r in journal["insertions"] if r["table"] == "catalog_publications"]
    for row in publications:
        current = conn.execute("SELECT * FROM catalog_publications WHERE master_product_id=?", (row["key"],)).fetchone()
        if not current or dict(current) != row["after"]:
            raise ValueError("Independent publication edit prevents rollback")
    for row in publications:
        conn.execute("UPDATE catalog_publications SET is_visible=0 WHERE master_product_id=?", (row["key"],))
    return len(publications)


def summary(operations):
    out = {}
    for supplier in sorted({o["supplier"] for o in operations}):
        subset = [o for o in operations if o["supplier"] == supplier]
        out[supplier] = {"source_rows": sum(len(o["sources"]) for o in subset), "identities": len(subset),
                         **{action: sum(o["action"] == action for o in subset) for action in ["create", "match", "review", "skip", "source_update"]}}
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--reviewed-source-changes", type=Path)
    args = parser.parse_args()
    if args.confirm and (not args.expected_plan_sha256 or not args.journal):
        parser.error("Apply requires a reviewed plan hash and a new private journal")
    # This task's writer is intentionally restricted to its isolated candidate.
    allowed = Path(__file__).resolve().parents[2] / "data/catalog-import-20261006/candidate.db"
    if args.confirm:
        if args.database.resolve() != allowed or any(p.is_symlink() for p in [args.database, *args.database.parents]) or args.database.stat().st_nlink != 1:
            parser.error("This importer is restricted to the isolated task candidate without links; use the release safety process for Production")
    conn = sqlite3.connect("file:" + str(args.database.resolve()) + ("?mode=rw" if args.confirm else "?mode=ro"), uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("BEGIN IMMEDIATE" if args.confirm else "BEGIN")
    try:
        rows = json.loads(args.rows.read_text())
        operations = plan(conn, rows, json.loads(args.reviewed_source_changes.read_text()) if args.reviewed_source_changes else None)
        checksum = digest(operations)
        result = {"confirmed": args.confirm, "plan_sha256": checksum, "summary": summary(operations), "operations": operations}
        if args.confirm:
            if checksum != args.expected_plan_sha256:
                raise ValueError("Catalog changed after preview")
            journal = apply(conn, operations)
            # Capture every column, including legacy schema defaults, so the
            # rollback check rejects independently edited publications.
            for entry in journal:
                key = "master_product_id" if entry["table"] == "catalog_publications" else "id"
                entry["after"] = dict(conn.execute("SELECT * FROM " + entry["table"] + " WHERE " + key + "=?", (entry["key"],)).fetchone())
            if conn.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Foreign key violation")
            fd = os.open(args.journal, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"plan_sha256": checksum, "insertions": journal, "rollback": "hide created publications only after exact after-image checks; pending mappings and original provenance retained"}, f, ensure_ascii=False, indent=2)
                f.flush(); os.fsync(f.fileno())
            conn.commit()
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(dumps({k: result[k] for k in ["confirmed", "plan_sha256", "summary"]}))
    finally:
        if conn.in_transaction: conn.rollback()
        conn.close()


if __name__ == "__main__":
    main()
