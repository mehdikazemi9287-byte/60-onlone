"""Phase 6 — category attribute schemas, typed values, variation themes, listing quality, facets, seed, offer gate."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from app.api.v1 import catalog_schema
from app.core.errors import ValidationError
from app.services import catalog_quality_service as cq
from app.services import catalog_schema_service as cs
from app.services import marketplace_offer_service as offers
from tests.base import AppTestCase

SEED_SQL = Path(__file__).resolve().parents[1] / "migrations" / "0065_catalog_taxonomy_seed.sql"


class Phase6Base(AppTestCase):
    def setUp(self):
        super().setUp()
        if catalog_schema.bp.name not in self.app.blueprints:  # registered by app/main.py
            self.app.register_blueprint(catalog_schema.bp)
        os.environ.pop("CATALOG_ENFORCE_REQUIRED", None)

    def tearDown(self):
        os.environ.pop("CATALOG_ENFORCE_REQUIRED", None)
        super().tearDown()

    def cat(self, conn, slug):
        return cs.category_by_slug(conn, slug)["id"]

    def master(self, slug_cat: str, *, name="روغن مایع آفتابگردان لادن ۸۱۰ گرم", brand="لادن", family_id=None, sku=True,
               attributes_json=None, net_quantity=None, images=("https://x/1.jpg",), price=None) -> dict:
        with self.db.write_transaction() as conn:
            cid = self.cat(conn, slug_cat)
            if family_id is None:
                family_id = conn.execute("INSERT INTO product_families (slug, title_fa, brand, category_id) VALUES (?,?,?,?)",
                                         (f"fam-{uuid.uuid4().hex[:8]}", name, brand, cid)).lastrowid
            mid = conn.execute("""INSERT INTO master_products (public_product_id, canonical_name_fa, brand, family_id, attributes_json, net_quantity,
                                  image_urls_json, description_fa, provenance) VALUES (?,?,?,?,?,?,?,?, 'real')""",
                               (uuid.uuid4().hex, name, brand, family_id, attributes_json, net_quantity, json.dumps(list(images)),
                                "توضیحات کامل این کالا برای آزمون کیفیت فهرست‌گذاری نوشته شده و از پنجاه نویسه بیشتر است.")).lastrowid
            pid = None
            if sku:
                pid = conn.execute("""INSERT INTO products (slug, sku, title_fa, category_id, base_price_minor, master_product_id, provenance)
                                      VALUES (?,?,?,?,0,?, 'real')""", (f"p6-{uuid.uuid4().hex[:10]}", f"P6-{uuid.uuid4().hex[:8]}", name, cid, mid)).lastrowid
                conn.execute("INSERT INTO inventory (product_id, quantity_available) VALUES (?, 0)", (pid,))
        return {"master_id": mid, "family_id": family_id, "product_id": pid, "category_id": cid}


class SchemaTest(Phase6Base):
    def test_inheritance_and_override(self):
        with self.db.read_transaction() as conn:
            milk = {a["code"]: a for a in cs.effective_schema(conn, self.cat(conn, "supermarket--dairy--milk"))}
            canned = {a["code"]: a for a in cs.effective_schema(conn, self.cat(conn, "supermarket--canned--canned-fish"))}
        # inherited from the food vertical
        self.assertEqual(milk["halal"]["defined_at"], "supermarket")
        self.assertTrue(milk["halal"]["is_filterable"])
        # dairy overrides: shelf life in days required instead of months; storage becomes required
        self.assertFalse(milk["shelf_life_months"]["required"])
        self.assertEqual(milk["shelf_life_months"]["overridden_at"], "supermarket--dairy")
        self.assertTrue(milk["shelf_life_days"]["required"] and milk["storage"]["required"])
        self.assertTrue(milk["volume_ml"]["required"] and milk["volume_ml"]["is_variant_axis"])
        self.assertTrue(canned["shelf_life_months"]["required"] and canned["weight_g"]["required"])
        self.assertNotIn("shelf_life_days", canned)
        self.assertEqual(canned["weight_g"]["display_group_fa"], "ابعاد و وزن")

    def test_inherit_zero_stops_propagation_and_admin_override(self):
        h = self.admin_headers()
        with self.db.read_transaction() as conn:
            dairy, milk = self.cat(conn, "supermarket--dairy"), self.cat(conn, "supermarket--dairy--milk")
        r = self.client.put(f"/api/v1/admin/catalog/categories/{dairy}/attributes/flavor", headers=h,
                            json={"required": 1, "is_filterable": 1, "inherit": 0, "display_group_fa": "مشخصات کلی"})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertIn("flavor", [a["code"] for a in r.get_json()["effective"]])
        with self.db.read_transaction() as conn:
            self.assertNotIn("flavor", [a["code"] for a in cs.effective_schema(conn, milk)])
        # child override: halal required only at milk
        r = self.client.put(f"/api/v1/admin/catalog/categories/{milk}/attributes/halal", headers=h, json={"required": 1})
        eff = {a["code"]: a for a in r.get_json()["effective"]}
        self.assertTrue(eff["halal"]["required"] and eff["halal"]["is_filterable"])  # filterable still inherited
        self.assertEqual(self.client.put(f"/api/v1/admin/catalog/categories/{milk}/attributes/halal", json={}).status_code, 401)

    def test_public_schema_endpoint(self):
        r = self.client.get("/api/v1/categories/supermarket--oil--liquid/schema")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        codes = {a["code"]: a for a in d["attributes"]}
        self.assertTrue(codes["oil_type"]["required"])
        self.assertIn("آفتابگردان", [o["label_fa"] for o in codes["oil_type"]["options"]])
        self.assertEqual(d["variation_theme"]["axes"], ["volume_ml", "pack_count"])
        self.assertEqual(d["policy"]["tax_category"], "FOOD_BASIC")
        self.assertEqual(d["seo"]["canonical_path"], "/category/supermarket--oil--liquid")  # matches the storefront route
        self.assertEqual(self.client.get("/api/v1/categories/no-such/schema").status_code, 404)


class ValueTest(Phase6Base):
    def _a(self, conn, code):
        a = cs.definition(conn, code)
        a["attribute_id"] = a["id"]
        return a

    def test_unit_normalization_and_digits(self):
        with self.db.read_transaction() as conn:
            w, v, ln, p = (self._a(conn, c) for c in ("weight_g", "volume_ml", "length_mm", "power_w"))
            self.assertEqual(cs.parse_measure(conn, w, "۱٫۵ کیلوگرم"), (1_500_000, "kg"))
            self.assertEqual(cs.parse_measure(conn, w, "500g"), (500_000, "g"))
            self.assertEqual(cs.parse_measure(conn, w, "۸۱۰ گرم"), (810_000, "g"))
            self.assertEqual(cs.parse_measure(conn, w, 900), (900_000, "g"))
            self.assertEqual(cs.parse_measure(conn, v, "1.5 L"), (1_500_000, "l"))
            self.assertEqual(cs.parse_measure(conn, v, {"value": 250, "unit": "ml"}), (250_000, "ml"))
            self.assertEqual(cs.parse_measure(conn, ln, "۲۰ سانت"), (200_000, "cm"))
            self.assertEqual(cs.parse_measure(conn, ln, "0.7mm"), (700, "mm"))
            self.assertEqual(cs.parse_measure(conn, p, "2.2kW"), (2_200_000, "kw"))
            with self.assertRaises(ValidationError) as cm:
                cs.parse_measure(conn, w, "2 لیتر")
            self.assertEqual(cm.exception.code, "attribute_invalid_unit")
            self.assertIn("واحدهای مجاز", str(cm.exception))
            self.assertEqual(cs.coerce(conn, self._a(conn, "pack_count"), "۱۲")[0]["value_number"], 12_000)
            with self.assertRaises(ValidationError):
                cs.coerce(conn, self._a(conn, "pack_count"), "1.5")
            with self.assertRaises(ValidationError) as cm:
                cs.coerce(conn, w, "2000 کیلوگرم")  # max 1 000 000 g
            self.assertEqual(cm.exception.code, "attribute_out_of_range")
            self.assertEqual(cs._display_measure(conn, "weight", 1_500_000), "۱٫۵ کیلوگرم")

    def test_enum_boolean_text_date_validation(self):
        with self.db.read_transaction() as conn:
            oil = self._a(conn, "oil_type")
            self.assertEqual(cs.coerce(conn, oil, "آفتابگردان")[0]["value_text"], "sunflower")
            self.assertEqual(cs.coerce(conn, oil, "canola")[0]["value_text"], "canola")
            with self.assertRaises(ValidationError) as cm:
                cs.coerce(conn, oil, "نارگیل")
            self.assertEqual(cm.exception.code, "attribute_invalid_option")
            self.assertIn("گزینه‌های مجاز", str(cm.exception))
            ink = cs.coerce(conn, self._a(conn, "ink_color"), "آبی، مشکی")
            self.assertEqual([r["value_key"] for r in ink], ["blue", "black"])
            self.assertEqual(cs.coerce(conn, self._a(conn, "halal"), "بله")[0]["value_bool"], 1)
            with self.assertRaises(ValidationError):
                cs.coerce(conn, self._a(conn, "model_code"), "مدل فارسی")  # regex: Latin only
            with self.assertRaises(ValidationError):
                cs.coerce(conn, {"name_fa": "تاریخ", "data_type": "date", "code": "d"}, "1403/01/01")
            self.assertEqual(cs.coerce(conn, {"name_fa": "تاریخ", "data_type": "date", "code": "d"}, "۲۰۲۶-۰۱-۰۲")[0]["value_text"], "2026-01-02")

    def test_set_values_and_spec_groups(self):
        m = self.master("supermarket--oil--liquid")
        with self.db.write_transaction() as conn:
            with self.assertRaises(ValidationError) as cm:
                cs.set_values(conn, m["master_id"], {"oil_type": "نارگیل", "gsm": "80"})
            self.assertEqual(len(cm.exception.details["errors"]), 2)
            cs.set_values(conn, m["master_id"], {"volume_ml": "۸۱۰ میلی‌لیتر", "oil_type": "آفتابگردان", "halal": True, "pack_count": 1})
            vals = cs.get_values(conn, m["master_id"])
            self.assertEqual(vals, {"volume_ml": 810, "oil_type": "sunflower", "halal": True, "pack_count": 1})
            groups = {g["group_fa"]: g["items"] for g in cs.spec_groups(conn, m["master_id"], m["category_id"])}
            self.assertIn("ابعاد و وزن", groups)
            self.assertEqual(next(i for i in groups["ابعاد و وزن"] if i["code"] == "volume_ml")["value_fa"], "۸۱۰ میلی‌لیتر")
            self.assertEqual(next(i for i in groups["مشخصات کلی"] if i["code"] == "oil_type")["value_fa"], "آفتابگردان")


class ThemeTest(Phase6Base):
    def test_variation_theme_check(self):
        a = self.master("supermarket--dairy--milk", name="شیر کم‌چرب ۱ لیتری")
        b = self.master("supermarket--dairy--milk", name="شیر کم‌چرب ۲۰۰ میلی‌لیتری", family_id=a["family_id"])
        with self.db.write_transaction() as conn:
            cs.set_values(conn, a["master_id"], {"volume_ml": "1 لیتر", "pack_count": 1, "fat_percent": "1.5"})
            cs.set_values(conn, b["master_id"], {"volume_ml": "1000 ml", "pack_count": 1, "fat_percent": "1.5"})
            r = cs.check_family(conn, a["family_id"])
            self.assertFalse(r["ok"])
            self.assertEqual([e["code"] for e in r["errors"]], ["variant_duplicate"])
            cs.set_values(conn, b["master_id"], {"volume_ml": "200 ml", "fat_percent": "3"})
            r = cs.check_family(conn, a["family_id"])
            self.assertEqual([e["code"] for e in r["errors"]], ["variant_non_axis_differs"])
            cs.set_values(conn, b["master_id"], {"fat_percent": "1.5", "pack_count": None})
            r = cs.check_family(conn, a["family_id"])
            self.assertEqual(r["errors"][0]["code"], "variant_axis_missing")
            cs.set_values(conn, b["master_id"], {"pack_count": "6"})
            self.assertTrue(cs.check_family(conn, a["family_id"])["ok"])
        h = self.admin_headers()
        d = self.client.get(f"/api/v1/admin/catalog/families/{a['family_id']}/variation-check", headers=h).get_json()
        self.assertEqual(d["theme"]["axes"], ["volume_ml", "pack_count"])


class QualityTest(Phase6Base):
    def test_score_checklist_and_title(self):
        m = self.master("supermarket--oil--liquid", name="بهترین روغن")
        with self.db.write_transaction() as conn:
            low = cq.master_quality(conn, m["master_id"])
            self.assertEqual(set(low["missing_required"]), {"volume_ml", "oil_type", "shelf_life_months"})
            msgs = " ".join(c["message_fa"] for c in low["checklist"] if not c["ok"])
            self.assertIn("مشخصهٔ الزامی «نوع روغن»", msgs)
            self.assertIn("واژه‌های غیرمجاز", msgs)
            self.assertIn("نام برند", msgs)
            cs.set_values(conn, m["master_id"], {"volume_ml": "810ml", "oil_type": "sunflower", "shelf_life_months": 18,
                                                  "storage": "cool_dry", "origin": "ایران", "halal": True, "packaging": "bottle",
                                                  "pack_count": 1, "weight_g": "750g", "ingredients": "روغن آفتابگردان"})
            conn.execute("UPDATE master_products SET canonical_name_fa='روغن مایع آفتابگردان لادن ۸۱۰ میلی‌لیتر' WHERE id=?", (m["master_id"],))
            high = cq.master_quality(conn, m["master_id"])
            self.assertEqual(high["missing_required"], [])
            self.assertEqual(high["score"], 100)
            self.assertGreater(high["score"], low["score"])
            self.assertEqual(high["suggested_title"], "روغن مایع لادن ۷۵۰ گرم ۸۱۰ میلی‌لیتر")
            stored = conn.execute("SELECT score FROM catalog_quality_scores WHERE master_product_id=?", (m["master_id"],)).fetchone()[0]
            self.assertEqual(stored, 100)

    def test_seller_validate_endpoint(self):
        sup = self.create_test_supplier()
        body = {"category_slug": "stationery--paper--copy-paper", "title": "کاغذ A4 کپی‌مکس ۸۰ گرمی", "brand": "کپی‌مکس", "images": ["a", "b"],
                "attributes": {"paper_size": "A4", "gsm": "۸۰ گرم", "sheets_per_pack": "500", "color": "سبزآبی"}}
        r = self.client.post("/api/v1/supplier/catalog/validate", headers=sup["headers"], json=body)
        self.assertEqual(r.status_code, 200, r.get_json())
        d = r.get_json()
        self.assertFalse(d["valid"])
        self.assertEqual(d["errors"][0]["attribute"], "color")
        body["attributes"]["color"] = "سفید"
        d = self.client.post("/api/v1/supplier/catalog/validate", headers=sup["headers"], json=body).get_json()
        self.assertTrue(d["valid"], d)
        self.assertEqual(d["suggested_title"], "کاغذ تحریر و چاپ کپی‌مکس A4")
        _, cust = self.new_customer()
        self.assertEqual(self.client.post("/api/v1/supplier/catalog/validate", headers=cust, json=body).status_code, 403)


class FacetTest(Phase6Base):
    def test_attribute_filters_and_facets(self):
        made = []
        for vol, oil in (("810ml", "sunflower"), ("1.5 لیتر", "sunflower"), ("2.7 L", "canola")):
            m = self.master("supermarket--oil--liquid", name=f"روغن مایع {oil} {vol}", brand="لادن")
            with self.db.write_transaction() as conn:
                cs.set_values(conn, m["master_id"], {"volume_ml": vol, "oil_type": oil, "halal": True})
            made.append(m)
        base = "/api/v1/storefront/products?category=supermarket--oil--liquid&group=sku"
        d = self.client.get(base).get_json()
        self.assertEqual(d["total"], 3)
        facets = {f["code"]: f for f in d["attribute_facets"]}
        self.assertEqual({v["value"]: v["count"] for v in facets["oil_type"]["values"]}, {"sunflower": 2, "canola": 1})
        self.assertEqual(facets["volume_ml"]["min"], "810")
        self.assertEqual(facets["volume_ml"]["max"], "2700")
        self.assertIn("facets", d)  # existing fields kept
        d = self.client.get(base + "&attr.oil_type=sunflower").get_json()
        self.assertEqual(d["total"], 2)
        # disjunctive: oil_type counts ignore their own filter; volume counts narrow
        facets = {f["code"]: f for f in d["attribute_facets"]}
        self.assertEqual(sum(v["count"] for v in facets["oil_type"]["values"]), 3)
        self.assertEqual(sum(v["count"] for v in facets["volume_ml"]["values"]), 2)
        self.assertEqual(self.client.get(base + "&attr.volume_ml=1000..3000").get_json()["total"], 2)
        self.assertEqual(self.client.get(base + "&attr.volume_ml=1l..2l").get_json()["total"], 1)
        self.assertEqual(self.client.get(base + "&attr.volume_ml=..900").get_json()["total"], 1)
        self.assertEqual(self.client.get(base + "&attr.oil_type=sunflower,canola&attr.halal=1").get_json()["total"], 3)
        self.assertEqual(self.client.get(base + "&in_stock=1").get_json()["total"], 0)
        self.assertEqual(self.client.get(base + "&official=1").get_json()["total"], 0)
        bad = self.client.get(base + "&attr.oil_type=coconut")
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(self.client.get(base + "&attr.nope=1").status_code, 422)

    def test_product_detail_additions(self):
        m = self.master("supermarket--oil--liquid", name="روغن مایع لادن ۱.۵ لیتر")
        with self.db.write_transaction() as conn:
            cs.set_values(conn, m["master_id"], {"volume_ml": "1.5 L", "oil_type": "sunflower"})
            slug = conn.execute("SELECT slug FROM products WHERE id=?", (m["product_id"],)).fetchone()[0]
        d = self.client.get(f"/api/v1/storefront/products/{slug}").get_json()
        self.assertEqual(d["spec_groups"][0]["group_fa"], "ابعاد و وزن")
        self.assertIsNone(d["unit_price"])  # no verified price yet
        self.assertEqual(d["seo"]["breadcrumb_list"]["@type"], "BreadcrumbList")
        self.assertIn({"@type": "PropertyValue", "name": "نوع روغن", "value": "آفتابگردان"}, d["seo"]["product_jsonld"]["additionalProperty"])
        self.assertIn("شصت آنلاین", d["seo"]["meta_title"])
        with self.db.read_transaction() as conn:
            up = cq.unit_price(conn, m["master_id"], 1_200_000)
        self.assertEqual((up["basis"], up["price_minor"]), ("l", 800_000))


class SeedBackfillGateTest(Phase6Base):
    def _counts(self, conn):
        return tuple(conn.execute("""SELECT (SELECT COUNT(*) FROM categories), (SELECT COUNT(*) FROM attribute_definitions),
            (SELECT COUNT(*) FROM attribute_options), (SELECT COUNT(*) FROM category_attributes), (SELECT COUNT(*) FROM category_variation_themes),
            (SELECT COUNT(*) FROM category_listing_policies), (SELECT COUNT(*) FROM category_external_mappings)""").fetchone())

    def test_seed_idempotent_and_never_renames(self):
        with self.db.write_transaction() as conn:
            before = self._counts(conn)
            conn.execute("UPDATE categories SET name_fa='سوپرمارکت ویرایش‌شده' WHERE slug='supermarket'")
        self.assertGreaterEqual(before[0], 80)
        with self.db.write_transaction() as conn:
            for stmt in SEED_SQL.read_text(encoding="utf-8").split(";\n"):
                if stmt.strip() and not stmt.strip().startswith("--"):
                    conn.execute(stmt)
            self.assertEqual(self._counts(conn), before)
            self.assertEqual(conn.execute("SELECT name_fa FROM categories WHERE slug='supermarket'").fetchone()[0], "سوپرمارکت ویرایش‌شده")
            leaves = conn.execute("""SELECT COUNT(*) FROM categories c WHERE level='product_type'
                                     AND EXISTS (SELECT 1 FROM category_external_mappings x WHERE x.category_id=c.id AND x.source='torob')""").fetchone()[0]
            self.assertEqual(leaves, 52)
            # every seeded leaf has an effective schema and a variation theme
            for (cid,) in conn.execute("SELECT category_id FROM category_external_mappings WHERE source='torob'").fetchall():
                self.assertTrue(cs.effective_schema(conn, cid))
                self.assertIsNotNone(cs.variation_theme(conn, cid), cid)

    def test_backfill_counts_never_overwrites(self):
        a = self.master("supermarket--grains--legumes", name="عدس ۹۰۰ گرم", attributes_json=json.dumps({"weight_g": 900}), net_quantity="900 گرم")
        b = self.master("supermarket--grains--legumes", name="نخود", attributes_json=json.dumps({"weight_g": 900}), net_quantity="1 کیلوگرم")
        c = self.master("supermarket--grains--legumes", name="لوبیا", attributes_json=json.dumps({"weight_g": 500}))
        with self.db.write_transaction() as conn:
            cs.set_values(conn, c["master_id"], {"weight_g": "450g"})
            dry = cs.backfill(conn, dry_run=True)
            self.assertEqual((dry["inserted"], dry["ambiguous"], dry["skipped_existing"]), (1, 1, 1))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM product_attribute_values WHERE source='backfill'").fetchone()[0], 0)
        h = self.admin_headers()
        res = self.client.post("/api/v1/admin/catalog/attributes/backfill", headers=h, json={}).get_json()
        self.assertEqual(res["inserted"], 1)
        with self.db.read_transaction() as conn:
            self.assertEqual(cs.get_values(conn, a["master_id"])["weight_g"], 900)
            self.assertNotIn("weight_g", cs.get_values(conn, b["master_id"]))
            self.assertEqual(cs.get_values(conn, c["master_id"])["weight_g"], 450)
        self.assertEqual(self.client.post("/api/v1/admin/catalog/attributes/backfill", headers=h, json={}).get_json()["inserted"], 0)

    def test_offer_gate_warn_then_enforce(self):
        sup = self.create_test_supplier()
        m1 = self.master("supermarket--oil--liquid")
        m2 = self.master("supermarket--oil--liquid")
        data = lambda pid: {"product_id": pid, "selling_price_minor": 1_000_000, "stock_quantity": 5, "supplier_location_id": sup["location_id"]}
        with self.db.write_transaction() as conn:
            o = offers.create(conn, supplier_id=sup["supplier_id"], actor=sup["user_id"], data=data(m1["product_id"]))
        self.assertIn("attr:oil_type", [w["key"] for w in o["catalog_warnings"]])
        os.environ["CATALOG_ENFORCE_REQUIRED"] = "1"
        with self.db.write_transaction() as conn:
            with self.assertRaises(ValidationError) as cm:
                offers.create(conn, supplier_id=sup["supplier_id"], actor=sup["user_id"], data=data(m2["product_id"]))
        self.assertEqual(cm.exception.code, "catalog_required_attributes_missing")
        with self.db.write_transaction() as conn:
            cs.set_values(conn, m2["master_id"], {"volume_ml": "810ml", "oil_type": "sunflower", "shelf_life_months": 12})
            o2 = offers.create(conn, supplier_id=sup["supplier_id"], actor=sup["user_id"], data=data(m2["product_id"]))
        self.assertNotIn("catalog_warnings", o2)


class AdminCrudTest(Phase6Base):
    def test_definition_option_policy_theme_mapping_crud(self):
        h = self.admin_headers()
        r = self.client.post("/api/v1/admin/catalog/attributes", headers=h, json={
            "code": "roast_level", "name_fa": "درجه برشته‌کاری", "data_type": "enum", "options": [{"code": "light", "label_fa": "روشن"}]})
        self.assertEqual(r.status_code, 201, r.get_json())
        aid = r.get_json()["attribute"]["id"]
        self.assertEqual(self.client.post("/api/v1/admin/catalog/attributes", headers=h, json={
            "code": "roast_level", "name_fa": "x", "data_type": "enum"}).status_code, 409)
        self.assertEqual(self.client.post("/api/v1/admin/catalog/attributes", headers=h, json={
            "code": "bad_measure", "name_fa": "x", "data_type": "measure", "unit_kind": "weight", "canonical_unit": "ml"}).status_code, 422)
        self.assertEqual(self.client.post(f"/api/v1/admin/catalog/attributes/{aid}/options", headers=h,
                                          json={"code": "dark", "label_fa": "تیره"}).status_code, 201)
        with self.db.read_transaction() as conn:
            tea = self.cat(conn, "supermarket--tea--black-tea")
        self.client.put(f"/api/v1/admin/catalog/categories/{tea}/attributes/roast_level", headers=h, json={"is_filterable": 1})
        r = self.client.put(f"/api/v1/admin/catalog/categories/{tea}/policy", headers=h, json={"min_images": 4, "is_fragile": 1,
                                                                                              "required_attribute_codes": "roast_level"})
        eff = r.get_json()["effective"]
        self.assertEqual((eff["min_images"], eff["is_fragile"], eff["tax_category"]), (4, True, "STANDARD"))
        self.assertEqual(eff["sources"]["min_images"], "supermarket--tea--black-tea")
        self.assertEqual(eff["required_attribute_codes"], ["roast_level"])
        r = self.client.put(f"/api/v1/admin/catalog/categories/{tea}/themes/roast", headers=h, json={"name_fa": "برشته", "axes": ["roast_level", "weight_g"]})
        self.assertEqual(r.get_json()["default"]["axes"], ["roast_level", "weight_g"])
        self.assertEqual(self.client.put(f"/api/v1/admin/catalog/categories/{tea}/themes/x", headers=h,
                                         json={"name_fa": "x", "axes": ["gsm"]}).status_code, 422)
        r = self.client.put(f"/api/v1/admin/catalog/categories/{tea}/mappings", headers=h, json={"items": [{"source": "torob", "external_code": "T-12"}]})
        self.assertIn({"source": "torob", "external_code": "T-12", "external_name": None}, r.get_json()["items"])
        self.assertEqual(self.client.get("/api/v1/admin/catalog/attributes", headers=self.new_customer()[1]).status_code, 403)
