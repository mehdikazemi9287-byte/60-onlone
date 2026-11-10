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
