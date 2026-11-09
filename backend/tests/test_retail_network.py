"""Retail network: chains, sectors, branches, contract-status visibility, CSV import, coverage.

All chains and branches below are fictional test fixtures (names prefixed «آزمایشی»); they exist only in the
isolated per-test database.
"""
from __future__ import annotations

from tests.base import AppTestCase

SRC = {"data_source": "chain_file", "source_reference": "test-fixture.csv"}


class RetailNetworkTest(AppTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.admin = self.admin_headers()

    def _chain(self, slug="test-chain", status="active", sectors=("fmcg",), **extra):
        body = {"slug": slug, "name": f"زنجیرهٔ آزمایشی {slug}", "contract_status": status, "sectors": list(sectors),
                **({"contract_reference": "TEST-1"} if status == "active" else {}), **extra}
        r = self.client.post("/api/v1/admin/network/chains", json=body, headers=self.admin)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()

    def _branch(self, chain="test-chain", code="B1", province="تهران", city="تهران", status="active", **extra):
        body = {"chain_slug": chain, "branch_code": code, "province": province, "city": city,
                "contract_status": status, "latitude": 35.7, "longitude": 51.4, **SRC, **extra}
        r = self.client.post("/api/v1/admin/network/branches", json=body, headers=self.admin)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()

    def test_reference_data(self):
        cov = self.client.get("/api/v1/network/coverage").get_json()
        self.assertEqual(cov["totals"]["provinces"], 31)
        self.assertEqual(cov["totals"]["branches"], 0)
        slugs = {s["slug"] for s in self.client.get("/api/v1/network/sectors").get_json()["items"]}
        self.assertTrue({"fmcg", "nuts-dried-fruit", "carpet", "moquette", "stone"} <= slugs)

    def test_only_active_contracts_are_public(self):
        self._chain("live")
        self._chain("talks", status="negotiating")
        self._branch("live", "L1")
        self._branch("live", "L2", status="prospect")
        self._branch("talks", "T1")
        items = self.client.get("/api/v1/network").get_json()["items"]
        self.assertEqual([i["chain"]["slug"] for i in items], ["live"])
        self.assertNotIn("source_reference", items[0])  # admin-only fields never leak
        self.assertNotIn("contract_status", items[0])
        self.assertEqual(self.client.get("/api/v1/network/chains/talks").status_code, 404)
        chains = [c["slug"] for c in self.client.get("/api/v1/network/chains").get_json()["items"]]
        self.assertEqual(chains, ["live"])
        # admin sees all three branches and why they are hidden
        admin = self.client.get("/api/v1/admin/network/branches", headers=self.admin).get_json()["items"]
        self.assertEqual(sorted((b["branch_code"], b["public"]) for b in admin),
                         [("L1", True), ("L2", False), ("T1", False)])
        # pausing the chain hides its branches immediately
        cid = [c for c in self.client.get("/api/v1/admin/network/chains", headers=self.admin).get_json()["items"]
               if c["slug"] == "live"][0]["id"]
        self.client.put(f"/api/v1/admin/network/chains/{cid}", json={"contract_status": "paused"}, headers=self.admin)
        self.assertEqual(self.client.get("/api/v1/network").get_json()["items"], [])

    def test_test_provenance_chain_never_public(self):
        self._chain("fixture", provenance="test")
        self._branch("fixture", "F1")
        self.assertEqual(self.client.get("/api/v1/network").get_json()["items"], [])

    def test_activation_requires_contract_evidence(self):
        r = self.client.post("/api/v1/admin/network/chains", headers=self.admin,
                             json={"slug": "nocontract", "name": "آزمایشی", "contract_status": "active"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.get_json()["error"]["code"], "contract_evidence_required")

    def test_filters_and_coverage(self):
        self._chain("a", sectors=("fmcg",))
        self._chain("b", sectors=("carpet",))
        self._branch("a", "A1", province="تهران", city="تهران")
        self._branch("a", "A2", province="اصفهان", city="كاشان", latitude=33.98, longitude=51.43)  # Arabic ك
        self._branch("b", "B1", province="fars", city="شیراز", latitude=29.6, longitude=52.5)
        g = self.client.get
        self.assertEqual(len(g("/api/v1/network?province=isfahan").get_json()["items"]), 1)
        self.assertEqual(g("/api/v1/network?province=استان اصفهان").get_json()["items"][0]["city"], "کاشان")
        self.assertEqual(len(g("/api/v1/network?sector=carpet").get_json()["items"]), 1)
        self.assertEqual(len(g("/api/v1/network?chain=a").get_json()["items"]), 2)
        cov = g("/api/v1/network/coverage").get_json()
        self.assertEqual((cov["totals"]["provinces_covered"], cov["totals"]["branches"]), (3, 3))
        self.assertEqual(g("/api/v1/network/coverage?sector=carpet").get_json()["totals"]["branches"], 1)
        prov = g("/api/v1/network/provinces/isfahan").get_json()
        self.assertEqual(prov["cities"], [{"name": "کاشان", "branches": 1}])
        self.assertEqual(g("/api/v1/network/provinces/atlantis").status_code, 404)
        self.assertEqual(g("/api/v1/network?province=atlantis").status_code, 422)

    def test_branch_validation(self):
        self._chain("v")
        post = lambda **kw: self.client.post("/api/v1/admin/network/branches", headers=self.admin,
                                             json={"chain_slug": "v", "branch_code": "X", "province": "تهران",
                                                   "city": "تهران", **SRC, **kw})
        self.assertEqual(post(data_source="guess").status_code, 422)
        self.assertEqual(post(source_reference="").status_code, 422)
        self.assertEqual(post(latitude=51.4, longitude=35.7).status_code, 422)  # swapped
        self.assertEqual(post(latitude=35.7).status_code, 422)  # half a coordinate
        self.assertEqual(post(phone="call me").status_code, 422)
        self.assertEqual(post(chain_slug="nope").status_code, 422)
        self.assertEqual(post(phone="۰۲۱-۸۸۷۷۶۶۵۵").status_code, 201)
        self.assertEqual(post().status_code, 409)  # same chain + code

    def test_admin_only(self):
        _, cust = self.new_customer()
        for method, url in (("get", "/api/v1/admin/network/chains"), ("post", "/api/v1/admin/network/branches"),
                            ("post", "/api/v1/admin/network/branches/import")):
            r = getattr(self.client, method)(url, json={}, headers=cust)
            self.assertIn(r.status_code, (401, 403), url)
        self.assertEqual(self.client.get("/api/v1/admin/network/chains").status_code, 401)

    def test_csv_import_dry_run_then_commit(self):
        self._chain("csv")
        csv_text = ("﻿chain_slug,branch_code,title,province,city,latitude,longitude,contract_status,data_source,source_reference\n"
                    "csv,C1,شعبهٔ یک,تهران,تهران,35.7,51.4,active,chain_file,list-1404.xlsx\n"
                    "csv,C2,,خراسان رضوی,مشهد,36.3,59.6,active,chain_file,list-1404.xlsx\n"
                    "csv,C3,,ناکجا,هیچ,,,active,chain_file,list-1404.xlsx\n"
                    "csv,C1,تکراری,تهران,تهران,,,active,chain_file,list-1404.xlsx\n"
                    "csv,C4,,قم,قم,,,active,,\n")
        url = "/api/v1/admin/network/branches/import"
        dry = self.client.post(url, json={"csv": csv_text}, headers=self.admin).get_json()
        self.assertEqual((dry["committed"], dry["created"], dry["errors"]), (False, 2, 3))
        self.assertEqual([r["code"] for r in dry["results"] if r["action"] == "error"],
                         ["unknown_province", "duplicate_row", "missing_source"])
        self.assertEqual(self.client.get("/api/v1/admin/network/branches", headers=self.admin).get_json()["items"], [])
        done = self.client.post(url + "?commit=1", json={"csv": csv_text}, headers=self.admin).get_json()
        self.assertEqual((done["created"], done["errors"]), (2, 3))
        self.assertEqual(len(self.client.get("/api/v1/network").get_json()["items"]), 2)
        # re-import updates in place (keyed by chain + branch_code)
        again = self.client.post(url + "?commit=1", headers=self.admin, json={"csv":
            "chain_slug,branch_code,province,city,contract_status,data_source,source_reference\n"
            "csv,C2,خراسان رضوی,نیشابور,paused,contract,contract-77\n"}).get_json()
        self.assertEqual((again["updated"], again["created"], again["errors"]), (1, 0, 0))
        self.assertEqual(len(self.client.get("/api/v1/network").get_json()["items"]), 1)
        bad = self.client.post(url, headers=self.admin, json={"csv": "chain_slug,branch_code\ncsv,C9\n"})
        self.assertEqual(bad.get_json()["error"]["code"], "missing_columns")

    def test_sectors_admin(self):
        r = self.client.post("/api/v1/admin/network/sectors", json={"slug": "textile", "name": "پوشاک"}, headers=self.admin)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.client.post("/api/v1/admin/network/sectors", json={"slug": "textile", "name": "x"},
                                          headers=self.admin).status_code, 409)
        sid = r.get_json()["id"]
        self.client.put(f"/api/v1/admin/network/sectors/{sid}", json={"active": False}, headers=self.admin)
        public = {s["slug"] for s in self.client.get("/api/v1/network/sectors").get_json()["items"]}
        self.assertNotIn("textile", public)
        r = self.client.post("/api/v1/admin/network/chains", headers=self.admin,
                             json={"slug": "s", "name": "آزمایشی", "sectors": ["nope"]})
        self.assertEqual(r.get_json()["error"]["code"], "unknown_sector")


class NetworkFulfillmentLinkTest(AppTestCase):
    """Branch → supplier-location sync and organization coverage."""

    def setUp(self) -> None:
        super().setUp()
        self.admin = self.admin_headers()

    def _chain_with_branches(self, supplier_id=None):
        body = {"slug": "linked", "name": "زنجیرهٔ آزمایشی پیوسته", "contract_status": "active",
                "contract_reference": "TEST-2", "sectors": ["fmcg"]}
        if supplier_id is not None:
            body["supplier_id"] = supplier_id
        chain = self.client.post("/api/v1/admin/network/chains", json=body, headers=self.admin).get_json()
        for code, prov, city, status in (("K1", "تهران", "تهران", "active"), ("K2", "خراسان رضوی", "مشهد", "active"),
                                         ("K3", "قم", "قم", "negotiating")):
            r = self.client.post("/api/v1/admin/network/branches", headers=self.admin, json={
                "chain_slug": "linked", "branch_code": code, "province": prov, "city": city, "contract_status": status,
                "title": f"شعبهٔ {code}", "phone": "02100000000", **SRC})
            self.assertEqual(r.status_code, 201, r.get_json())
        return chain

    def test_sync_requires_supplier_link(self):
        chain = self._chain_with_branches()
        r = self.client.post(f"/api/v1/admin/network/chains/{chain['id']}/sync-locations", headers=self.admin)
        self.assertEqual(r.get_json()["error"]["code"], "chain_not_supplier")

    def test_sync_creates_inactive_locations_once(self):
        sup = self.create_test_supplier()
        chain = self._chain_with_branches(supplier_id=sup["supplier_id"])
        url = f"/api/v1/admin/network/chains/{chain['id']}/sync-locations"
        first = self.client.post(url, headers=self.admin).get_json()
        self.assertEqual(sorted(x["branch_code"] for x in first["created"]), ["K1", "K2"])  # not the negotiating one
        with self.db.read_transaction() as conn:
            locs = conn.execute(
                "SELECT province, city, status, can_pickup, can_local_delivery, can_intercity_shipping, public_title "
                "FROM supplier_locations WHERE id IN (%s) ORDER BY id" % ",".join(
                    str(x["supplier_location_id"]) for x in first["created"])).fetchall()
        self.assertEqual([(l["province"], l["city"]) for l in locs], [("تهران", "تهران"), ("خراسان رضوی", "مشهد")])
        self.assertTrue(all(l["status"] == "inactive" and not (l["can_pickup"] or l["can_local_delivery"]
                                                               or l["can_intercity_shipping"]) for l in locs))
        again = self.client.post(url, headers=self.admin).get_json()
        self.assertEqual((again["created"], again["linked_total"]), ([], 2))
        branches = self.client.get("/api/v1/admin/network/branches?chain=linked", headers=self.admin).get_json()["items"]
        self.assertEqual(sum(1 for b in branches if b["supplier_location_id"]), 2)

    def test_organization_coverage(self):
        self._chain_with_branches()
        product = self.product()
        self.set_stock(product["id"], 10)
        org, org_admin, _, employee = self.org_fixture(credit_minor=200_000_000)
        self.add_to_cart(employee["headers"], product["id"], 1)
        r = self.checkout(employee["headers"])
        self.assertIn(r.status_code, (200, 201), r.get_json())
        with self.db.write_transaction() as conn:
            row = conn.execute("SELECT id FROM orders WHERE organization_id=?", (org["id"],)).fetchone()
            self.assertIsNotNone(row, "employee checkout should record the organization on the order")
            # Second and third destinations: copies of the same real order with other cities (test DB only).
            cols = [c[1] for c in conn.execute("PRAGMA table_info(orders)") if c[1] != "id"]
            for n, (prov, city) in enumerate((("قم", "قم"), ("ناکجا", "هیچ‌جا"))):
                sel = ", ".join("?" if c in ("shipping_province", "shipping_city", "order_number") else c for c in cols)
                args = [v for c in cols for v in ((prov,) if c == "shipping_province" else (city,) if c == "shipping_city"
                                                   else (f"TEST-COV-{n}",) if c == "order_number" else ())]
                conn.execute(f"INSERT INTO orders ({', '.join(cols)}) SELECT {sel} FROM orders WHERE id=?", [*args, row["id"]])
        cov = self.client.get(f"/api/v1/organizations/{org['id']}/network-coverage", headers=org_admin)
        self.assertEqual(cov.status_code, 200, cov.get_json())
        data = cov.get_json()
        by_city = {p["city"]: p["coverage"] for p in data["places"]}
        self.assertEqual(by_city, {"تهران": "city", "قم": "none"})  # Qom branch is only negotiating
        self.assertEqual(data["unresolved_places"][0]["province"], "ناکجا")
        # employees (non-admin members) cannot read it
        self.assertEqual(self.client.get(f"/api/v1/organizations/{org['id']}/network-coverage",
                                         headers=employee["headers"]).status_code, 403)
