"""Performance regressions with isolated synthetic AppTestCase data only."""
from unittest.mock import patch
from tests.base import AppTestCase
from app.services import sale_eligibility as eligibility


class CatalogPerformanceTest(AppTestCase):
    def test_batch_matches_single_offer_policy_and_bounded_query_count(self):
        ids = [r['id'] for r in self.db.query('SELECT id FROM products')]
        with self.app.app_context():
            expected = {pid: eligibility.eligible_offer_db(self.db, pid) for pid in ids}
            with patch.object(self.db, 'query', wraps=self.db.query) as query:
                actual = eligibility.eligible_offers_db(self.db, ids + ids)
            self.assertEqual(query.call_count, 2)
            for pid, row in expected.items():
                self.assertEqual({k: actual[pid][k] for k in row.keys()}, dict(row))

    def test_disabled_sales_does_not_query_offers(self):
        self.app.config.update(TEST_SALES_OVERRIDE=False, STOREFRONT_SALES_ENABLED=False, COMMERCE_TEST_MODE=False)
        with self.app.app_context(), patch.object(self.db, 'query', wraps=self.db.query) as query:
            self.assertEqual(eligibility.eligible_offers_db(self.db, [1, 2]), {})
            self.assertEqual(query.call_count, 0)

    def test_listing_does_not_call_single_product_offer_lookup(self):
        with patch.object(eligibility, 'eligible_offer_db', side_effect=AssertionError('N+1 regression')):
            response = self.client.get('/api/v1/products?page_size=5')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()['items']), 5)

    def test_offer_policy_preserves_freshness_channel_and_stock(self):
        supplier = self.create_test_supplier()
        product = self.create_test_product_with_offer(supplier['supplier_id'], supplier['location_id'])
        pid, oid = product['product_id'], product['offer_id']
        self.app.config.update(TEST_SALES_OVERRIDE=False, COMMERCE_TEST_MODE=True)
        with self.db.write_transaction() as c:
            c.execute("UPDATE suppliers SET provenance='test' WHERE id=?", (supplier['supplier_id'],))
            c.execute("UPDATE seller_offers SET provenance='test',channel='both',pricing_mode='fixed',last_price_confirmed_at=CURRENT_TIMESTAMP,last_inventory_confirmed_at=CURRENT_TIMESTAMP WHERE id=?", (oid,))
        with self.app.app_context():
            single = eligibility.eligible_offer_db(self.db, pid)
            batch = eligibility.eligible_offers_db(self.db, [pid])
            self.assertIsNotNone(single)
            self.assertEqual(batch[pid]['id'], single['id'])
            self.app.config.update(COMMERCE_TEST_MODE=False, STOREFRONT_SALES_ENABLED=True)
            self.assertEqual(eligibility.eligible_offers_db(self.db, [pid]), {})
            self.app.config.update(COMMERCE_TEST_MODE=True)
            for update in ["last_price_confirmed_at='2000-01-01'", "last_price_confirmed_at=CURRENT_TIMESTAMP,channel='organization'", "channel='both',stock_quantity=0"]:
                with self.db.write_transaction() as c:
                    c.execute('UPDATE seller_offers SET ' + update + ' WHERE id=?', (oid,))
                self.assertIsNone(eligibility.eligible_offer_db(self.db, pid))
                self.assertEqual(eligibility.eligible_offers_db(self.db, [pid]), {})

    def test_batch_chunks_parameters(self):
        self.app.config.update(TEST_SALES_OVERRIDE=False, COMMERCE_TEST_MODE=True)
        with self.app.app_context(), patch.object(self.db, 'query', return_value=[]) as query:
            self.assertEqual(eligibility.eligible_offers_db(self.db, range(1, 802)), {})
            self.assertEqual([len(c.args[1]) for c in query.call_args_list], [400, 400, 1])

    def test_sql_pagination_bounds_materialized_rows_for_every_sort(self):
        # Synthetic seeded data only. Ensure null prices remain last in either direction.
        with self.db.write_transaction() as c:
            c.execute("UPDATE products SET base_price_minor=0 WHERE id=(SELECT MIN(id) FROM products)")
        for sort in ("newest", "rating", "price_asc", "price_desc"):
            sizes = []
            real_query = self.db.query
            def measured(sql, params=()):
                result = real_query(sql, params)
                sizes.append(len(result))
                return result
            items = []
            with patch.object(self.db, "query", side_effect=measured):
                for page in range(1, 4):
                    response = self.client.get(f"/api/v1/products?page={page}&page_size=5&sort={sort}")
                    self.assertEqual(response.status_code, 200, response.get_json())
                    data = response.get_json()
                    self.assertEqual(data["total"], 14)
                    items.extend(data["items"])
            self.assertLessEqual(max(sizes), 5)
            self.assertEqual(len({i["id"] for i in items}), 14)
            if sort == "price_asc":
                expected = sorted(items, key=lambda i: (i["price_minor"] is None, i["price_minor"] or 0, -i["id"]))
            elif sort == "price_desc":
                expected = sorted(items, key=lambda i: (i["price_minor"] is not None, i["price_minor"] or 0, i["id"]), reverse=True)
            else:
                expected = sorted(items, key=lambda i: i["id"], reverse=True)
            self.assertEqual([i["id"] for i in items], [i["id"] for i in expected])
            empty = self.client.get(f"/api/v1/products?page=1000000000000000000000000000&page_size=5&sort={sort}").get_json()
            self.assertEqual(empty["items"], [])
            self.assertEqual(empty["total"], 14)

    def test_storefront_tiers_are_batched_and_org_prices_stay_private(self):
        from app.services import storefront_service as storefront
        from app.services import product_channel_policy as policy
        suppliers = [self.create_test_supplier() for _ in range(3)]
        products = [self.create_test_product_with_offer(supplier['supplier_id'], supplier['location_id']) for supplier in suppliers]
        pid = products[0]['product_id']
        self.app.config.update(TEST_SALES_OVERRIDE=False, COMMERCE_TEST_MODE=True)
        with self.db.write_transaction() as c:
            for supplier in suppliers:
                c.execute("UPDATE suppliers SET provenance='test' WHERE id=?", (supplier['supplier_id'],))
            for product in products:
                oid = product['offer_id']
                c.execute("UPDATE seller_offers SET product_id=?,provenance='test',channel='both',pricing_mode='fixed',last_price_confirmed_at=CURRENT_TIMESTAMP,last_inventory_confirmed_at=CURRENT_TIMESTAMP WHERE id=?", (pid, oid))
                for channel in ('retail', 'organization'):
                    c.execute("INSERT INTO offer_price_tiers(offer_id,channel,min_qty,unit_price_minor,confirmed_at) VALUES(?,?,1,100,CURRENT_TIMESTAMP)", (oid, channel))
        queries = []
        with self.app.app_context(), self.db.read_transaction() as c:
            c.set_trace_callback(queries.append)
            with patch.object(policy, 'sku_policy', wraps=policy.sku_policy) as sku_policy:
                offers = storefront.offers_for(c, pid)
                self.assertEqual(sku_policy.call_count, 1)
            c.set_trace_callback(None)
            self.assertEqual(len(offers), 3)
            self.assertTrue(all(len(o['tiers']['retail']) == 1 for o in offers))
            self.assertTrue(all(o['tiers']['organization'] == [] for o in offers))
            org_offers = storefront.offers_for(c, pid, viewer_org_ids=(123,))
            self.assertTrue(all(len(o['tiers']['organization']) == 1 for o in org_offers))
        self.assertEqual(sum('FROM offer_price_tiers WHERE offer_id IN' in query for query in queries), 1)
