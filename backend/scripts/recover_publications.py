"""Preview or restore researched publications; never enable sales."""

import argparse, json, sqlite3
from pathlib import Path


def recover(conn, manifest, confirm=False):
    conn.row_factory = sqlite3.Row
    planned = []
    skipped = []
    for row in manifest["records"]:
        mid = row["master_product_id"]
        master = conn.execute(
            "SELECT canonical_name_fa FROM master_products WHERE id=?", (mid,)
        ).fetchone()
        if not master or master["canonical_name_fa"] != row["canonical_name_fa"]:
            raise ValueError("Master identity mismatch: " + str(mid))
        if conn.execute(
            "SELECT 1 FROM products WHERE master_product_id=? AND is_active=1", (mid,)
        ).fetchone():
            skipped.append(mid)
            continue
        if not conn.execute(
            "SELECT 1 FROM categories WHERE slug=?", (row["category_slug"],)
        ).fetchone():
            raise ValueError("Missing category: " + row["category_slug"])
        existing = conn.execute(
            "SELECT * FROM catalog_publications WHERE master_product_id=?", (mid,)
        ).fetchone()
        if existing:
            if existing["slug"] != row["slug"]:
                raise ValueError("Slug conflict: " + str(mid))
            skipped.append(mid)
            continue
        planned.append(row)
    if confirm:
        with conn:
            for row in planned:
                conn.execute(
                    "INSERT INTO catalog_publications (master_product_id,slug,category_slug,verified_price_minor,currency,is_visible,is_purchasable,price_status,publication_reason,created_at,updated_at) VALUES (?,?,?,?,?,1,0,?,?,?,?)",
                    (
                        row["master_product_id"],
                        row["slug"],
                        row["category_slug"],
                        None,
                        row["currency"],
                        "pending",
                        row["publication_reason"],
                        row["created_at"],
                        row["updated_at"],
                    ),
                )
    return {
        "confirmed": confirm,
        "planned": len(planned),
        "skipped_ids": skipped,
        "master_ids": [r["master_product_id"] for r in planned],
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--database", required=True)
    p.add_argument("--confirm", action="store_true")
    a = p.parse_args()
    c = sqlite3.connect("file:" + a.database + "?mode=" + ("rw" if a.confirm else "ro"), uri=True)
    if not a.confirm:
        c.execute("PRAGMA query_only=ON")
    m = json.loads(
        (Path(__file__).resolve().parents[1] / "recovery/catalog_publications.json").read_text()
    )
    print(json.dumps(recover(c, m, a.confirm)))
    c.close()
