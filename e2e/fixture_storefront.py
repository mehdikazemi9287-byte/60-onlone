"""[TEST ONLY] E2E fixture: link seed products to master_products so the storefront lists them.

seed.py creates legacy `products` rows without master_products, and the storefront only lists
products joined to an active master. Synthetic rows are labeled provenance='test' (allowed only
when TEST_SALES_OVERRIDE / APP_ENV=test). Offers' freshness stamps are refreshed.
"""
import datetime, sqlite3, uuid
c = sqlite3.connect("/tmp/e2e/e2e.db"); c.row_factory = sqlite3.Row
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
cats = {r["id"]: r["slug"] for r in c.execute("SELECT id, slug FROM categories")}
n = 0
for p in c.execute("SELECT * FROM products WHERE master_product_id IS NULL").fetchall():
    cur = c.execute("""INSERT INTO master_products (public_product_id, canonical_name_fa, brand, category, unit,
        description_fa, tax_category, vat_applicable, vat_rate_bps, status, provenance, created_at, updated_at)
        VALUES (?,?,?,?,'عدد',?,'STANDARD',1,1000,'active','test',?,?)""",
        ("E2E-" + uuid.uuid4().hex[:10], p["title_fa"], p["brand_fa"], cats.get(p["category_id"]),
         p["description_fa"], now, now))
    c.execute("UPDATE products SET master_product_id=? WHERE id=?", (cur.lastrowid, p["id"]))
    n += 1
c.execute("UPDATE seller_offers SET last_price_confirmed_at=?, last_inventory_confirmed_at=?", (now, now))
c.commit()
print("linked", n)
