"""Synthetic intake fixtures; AppTestCase creates temporary SQLite DBs only."""
from copy import deepcopy
from tests.base import AppTestCase
from tests.test_procurement import _make_org_with_admin, _register_member


class OrganizationIntakeTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.org, self.admin, _ = _make_org_with_admin(self)
        self.member, self.uid = _register_member(self, self.org['id'])
        self.path = f"/api/v1/orgs/{self.org['id']}/procurement/requests"
        self.body = {'title': 'درخواست مصنوعی ایزوله', 'needed_by_date': '2026-12-01',
                     'budget_minor': 120000, 'substitution_policy': 'disallow',
                     'items': [{'free_text_description': 'قلم بدون قیمت آزمون', 'quantity': 5, 'unit': 'عدد'},
                               {'free_text_description': 'قلم دوم آزمون', 'quantity': 2, 'unit': 'بسته'}],
                     'destinations': [
                         {'province': 'استان آزمون', 'city': 'شهر آزمون', 'address': 'نشانی مصنوعی اول',
                          'allocations': [{'item_index': 0, 'quantity': 3}, {'item_index': 1, 'quantity': 1}]},
                         {'province': 'استان آزمون', 'city': 'شهر آزمون', 'address': 'نشانی مصنوعی دوم',
                          'allocations': [{'item_index': 0, 'quantity': 2}, {'item_index': 1, 'quantity': 1}]}]}

    def create(self, body=None, headers=None):
        return self.client.post(self.path, json=self.body if body is None else body,
                                headers=self.member if headers is None else headers)

    def snapshot(self):
        # The approver's in-app notice is expected; it is not a business side effect.
        allowed = {'purchase_requests', 'purchase_request_items', 'procurement_audit_log',
                   'idempotency_keys', 'sqlite_sequence', 'user_notifications'}
        with self.db.read_transaction() as conn:
            names = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            return {r['name']: [tuple(row) for row in conn.execute('SELECT * FROM "' + r['name'] + '"')]
                    for r in names if r['name'] not in allowed}

    def test_receipt_replay_submit_without_business_side_effects(self):
        before = self.snapshot()
        h = {**self.member, 'Idempotency-Key': 'synthetic-double-click'}
        a = self.create(headers=h)
        self.assertEqual(a.status_code, 201, a.get_json())
        pr = a.get_json()['purchase_request']
        self.assertEqual(pr['next_action'], 'submit_request')
        self.assertRegex(pr['request_number'], r'^PR-\d{8}-\d{4}$')
        self.assertEqual(pr['destinations'][1]['allocations'][0]['quantity'], 2)
        self.assertIsNone(pr['items'][0]['estimated_unit_price_minor'])
        replay = self.create(headers=h)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(a.get_json(), replay.get_json())
        self.assertEqual(self.create({**self.body, 'title': 'تغییر'}, h).status_code, 409)
        url = f"{self.path}/{pr['id']}/submit"
        submit = self.client.post(url, headers=self.member)
        self.assertEqual(submit.status_code, 200, submit.get_json())
        self.assertEqual(submit.get_json()['purchase_request']['next_action'], 'wait_for_review')
        self.assertEqual(self.client.post(url, headers=self.member).status_code, 409)
        self.assertEqual(before, self.snapshot())
        with self.db.read_transaction() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM purchase_requests').fetchone()[0], 1)
            self.assertEqual([r[0] for r in conn.execute('SELECT event_type FROM procurement_audit_log ORDER BY id')],
                             ['pr_created', 'pr_submitted'])

    def test_catalog_item_with_and_without_estimate(self):
        # Explicitly synthetic master product, only inside this temporary test DB.
        with self.db.write_transaction() as conn:
            product_id = conn.execute(
                "INSERT INTO master_products(public_product_id,canonical_name_fa) VALUES (?,?)",
                ('synthetic-intake-product', 'کالای مصنوعی آزمون ایزوله'),
            ).lastrowid
        for estimate in (None, 12345):
            body = deepcopy(self.body)
            body['items'][0] = {'master_product_id': product_id, 'quantity': 5,
                                'unit': 'عدد', 'estimated_unit_price_minor': estimate}
            response = self.create(body)
            self.assertEqual(response.status_code, 201, response.get_json())
            item = response.get_json()['purchase_request']['items'][0]
            self.assertEqual(item['master_product_id'], product_id)
            self.assertEqual(item['estimated_unit_price_minor'], estimate)

    def test_visibility_and_permissions(self):
        pr = self.create().get_json()['purchase_request']
        url = f"{self.path}/{pr['id']}"
        other, _ = _register_member(self, self.org['id'])
        self.assertEqual(self.client.get(url, headers=other).status_code, 404)
        self.assertEqual(self.client.get(self.path + f'?requester_user_id={self.uid}', headers=other).get_json()['items'], [])
        for suffix in ('submit', 'cancel'):
            self.assertEqual(self.client.post(url + '/' + suffix, headers=other).status_code, 403)
        for role, procurement in [('organization_admin', None), ('organization_finance', None),
                                 ('procurement_agent', None), ('employee', 'approver'), ('employee', 'procurement_officer')]:
            h, _ = _register_member(self, self.org['id'], role, procurement)
            self.assertEqual(self.client.get(url, headers=h).status_code, 200)
            self.assertEqual(len(self.client.get(self.path, headers=h).get_json()['items']), 1)
            if role == 'organization_finance':
                self.assertEqual(self.client.post(url + '/approve', json={'action': 'approve'}, headers=h).status_code, 403)
        _, outsider = self.new_customer()
        self.assertEqual(self.client.get(url, headers=outsider).status_code, 403)
        self.assertEqual(self.create(headers=outsider).status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 401)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE organization_memberships SET status='inactive' WHERE user_id=?", (self.uid,))
        self.assertEqual(self.client.get(url, headers=self.member).status_code, 403)

    def test_global_numbers_cross_org_and_cancel(self):
        first = self.create().get_json()['purchase_request']
        org, h, _ = _make_org_with_admin(self)
        path = f"/api/v1/orgs/{org['id']}/procurement/requests"
        response = self.client.post(path, json=self.body, headers=h)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertNotEqual(first['request_number'], response.get_json()['purchase_request']['request_number'])
        self.assertEqual(self.client.get(f"{path}/{first['id']}", headers=h).status_code, 404)
        self.assertEqual(self.client.get(f"{self.path}/{first['id']}", headers=h).status_code, 403)
        cancelled = self.client.post(f"{self.path}/{first['id']}/cancel", headers=self.member)
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.get_json()['purchase_request']['status'], 'cancelled')
        self.assertEqual(cancelled.get_json()['purchase_request']['destinations'], first['destinations'])

    def test_inactive_organization_blocks_intake_preserves_tracking(self):
        headers = {**self.member, 'Idempotency-Key': 'inactive-org-replay'}
        response = self.create(headers=headers)
        self.assertEqual(response.status_code, 201, response.get_json())
        pr = response.get_json()['purchase_request']
        url = f"{self.path}/{pr['id']}"
        for status in ('pending', 'suspended', 'inactive'):
            with self.subTest(status=status):
                with self.db.write_transaction() as conn:
                    conn.execute("UPDATE organizations SET status=? WHERE id=?", (status, self.org['id']))
                self.assertEqual(self.create().status_code, 403)
                self.assertEqual(self.create(headers=headers).status_code, 403)
                self.assertEqual(self.client.post(url + '/submit', headers=self.member).status_code, 403)
                tracked = self.client.get(url, headers=self.member)
                self.assertEqual(tracked.status_code, 200)
                self.assertEqual(tracked.get_json()['purchase_request']['status'], 'draft')
                self.assertEqual(len(self.client.get(self.path, headers=self.member).get_json()['items']), 1)
        with self.db.read_transaction() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM purchase_requests').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM procurement_audit_log').fetchone()[0], 1)

    def test_validation_rollback(self):
        invalid = [{**self.body, k: v} for k, v in [
            ('budget_minor', True), ('budget_minor', '100'), ('budget_minor', -1),
            ('needed_by_date', '2026-02-30'), ('needed_by_date', '20261201'),
            ('notes', {}), ('substitution_policy', 'automatic'), ('attachments', []),
            ('destinations', []), ('destinations', {})]]
        for field, value in [('quantity', True), ('quantity', 1.5), ('unit', ''), ('unit', {}),
                             ('estimated_unit_price_minor', -1), ('estimated_unit_price_minor', '12'),
                             ('notes', []), ('free_text_description', '   '), ('files', [])]:
            body = deepcopy(self.body)
            body['items'][0][field] = value
            invalid.append(body)
        # Partial allocation is allowed (completed before a PO); over-allocation is not.
        for field, value in [('quantity', 4), ('quantity', True), ('item_index', 99), ('item_index', False)]:
            body = deepcopy(self.body)
            body['destinations'][0]['allocations'][0][field] = value
            invalid.append(body)
        body = deepcopy(self.body)
        body['destinations'][0]['allocations'][1]['item_index'] = 0
        invalid.append(body)
        for body in invalid:
            with self.subTest(body=body):
                response = self.create(body)
                self.assertEqual(response.status_code, 422, response.get_json())
        with self.db.read_transaction() as conn:
            for table in ('purchase_requests', 'purchase_request_items', 'procurement_audit_log', 'idempotency_keys'):
                self.assertEqual(conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)
