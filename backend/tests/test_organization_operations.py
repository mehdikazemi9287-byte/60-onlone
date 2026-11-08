"""Isolated synthetic staff mandates: never provision runtime business grants."""
import sqlite3
import uuid

from tests.base import AppTestCase
from tests.test_procurement import _create_pr_direct, _register_member


class OperationsCaseTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.org = self.create_organization()['id']
        self.manager_h, self.manager = _register_member(self, self.org)
        self.agent_h, self.agent = _register_member(self, self.org)
        self.grant(self.manager, 'case_manager')
        self.grant(self.agent, 'case_agent')
        self.pr = _create_pr_direct(self, self.org, self.manager)
        self.url = f'/api/v1/internal/organizations/{self.org}/cases'

    def grant(self, user_id, capability, org=None):
        with self.db.write_transaction() as conn:
            conn.execute('INSERT INTO organization_operations_grants VALUES (?,?,?,?,?)',
                         (org or self.org, user_id, capability, 'active', 'ISOLATED TEST mandate'))

    def post(self, suffix='', data=None, headers=None, key=None, expected=200):
        resp = self.client.post(self.url + suffix, json=data,
                                headers={**(headers or self.manager_h), 'Idempotency-Key': key or uuid.uuid4().hex})
        self.assertEqual(resp.status_code, expected, resp.get_json())
        return resp.get_json()

    def create(self):
        return self.post(data={'purchase_request_id': self.pr['id'], 'reason': 'دریافت درخواست'})['case']

    def assign(self, case):
        return self.post(f"/{case['id']}/assign", {'assignee_user_id': self.agent,
                        'expected_version': case['version'], 'reason': 'تخصیص مسئول'})['case']

    def test_default_denial_platform_admin_customer_and_other_org(self):
        for headers in [self.admin_headers(), self.make_org_admin(self.org)[0]]:
            self.assertEqual(self.client.get(self.url, headers=headers).status_code, 403)
            self.post(data={'purchase_request_id': self.pr['id'], 'reason': 'test'}, headers=headers, expected=403)
        other = self.create_organization()['id']
        self.assertEqual(self.client.get(f'/api/v1/internal/organizations/{other}/cases', headers=self.manager_h).status_code, 403)
        _, other_user = _register_member(self, other)
        other_pr = _create_pr_direct(self, other, other_user)
        self.post(data={'purchase_request_id': other_pr['id'], 'reason': 'test'}, expected=404)

    def test_case_lifecycle_no_procurement_or_financial_side_effects(self):
        tables = ['purchase_requests', 'purchase_orders', 'orders', 'credit_reservations', 'credit_ledger_entries', 'ledger_entries', 'inventory']
        with self.db.read_transaction() as conn:
            before = {t: [dict(r) for r in conn.execute(f'SELECT * FROM {t}').fetchall()] for t in tables}
        case = self.assign(self.create())
        for status in ['sourcing', 'waiting_customer', 'blocked', 'triage', 'closed']:
            case = self.post(f"/{case['id']}/transition", {'status': status,
                             'expected_version': case['version'], 'reason': 'تغییر عملیاتی'}, self.agent_h)['case']
        self.post(f"/{case['id']}/transition", {'status': 'triage', 'expected_version': case['version'], 'reason': 'بازگشایی'}, expected=409)
        with self.db.read_transaction() as conn:
            after = {t: [dict(r) for r in conn.execute(f'SELECT * FROM {t}').fetchall()] for t in tables}
        self.assertEqual(before, after)
        details = self.client.get(f"{self.url}/{case['id']}", headers=self.manager_h).get_json()['case']
        self.assertEqual(len(details['events']), 7)
        self.assertEqual(details['version'], 7)

    def test_idempotency_payload_conflict_and_stale_version(self):
        data = {'purchase_request_id': self.pr['id'], 'reason': 'دریافت'}
        first = self.post(data=data, key='stable')
        self.assertEqual(first, self.post(data=data, key='stable'))
        self.post(data={**data, 'reason': 'متفاوت'}, key='stable', expected=409)
        case = self.assign(first['case'])
        data = {'status': 'sourcing', 'expected_version': case['version'], 'reason': 'تأمین'}
        result = self.post(f"/{case['id']}/transition", data, self.agent_h, 'transition')
        self.assertEqual(result, self.post(f"/{case['id']}/transition", data, self.agent_h, 'transition'))
        self.post(f"/{case['id']}/transition", data, self.agent_h, expected=409)
        with self.db.read_transaction() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM organization_operations_events').fetchone()['n'], 3)

    def test_revoked_actor_assignee_and_org_are_fail_closed(self):
        case = self.assign(self.create())
        data = {'status': 'sourcing', 'expected_version': case['version'], 'reason': 'تأمین'}
        self.post(f"/{case['id']}/transition", data, self.agent_h, 'old')
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE organization_operations_grants SET status='revoked' WHERE user_id=?", (self.agent,))
        self.assertEqual(self.client.get(f"{self.url}/{case['id']}", headers=self.agent_h).status_code, 403)
        self.post(f"/{case['id']}/transition", data, self.agent_h, 'old', expected=403)
        self.post(f"/{case['id']}/transition", {**data, 'expected_version': 3, 'status': 'blocked'}, expected=409)
        self.post(f"/{case['id']}/assign", {'assignee_user_id': self.manager, 'expected_version': 3, 'reason': 'مسئول جدید'})
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE organizations SET status='suspended' WHERE id=?", (self.org,))
        self.assertEqual(self.client.get(self.url, headers=self.manager_h).status_code, 403)

    def test_unassigned_inactive_out_of_scope_assignee_and_agent_restrictions(self):
        case = self.create()
        self.assertEqual(self.client.get(f"{self.url}/{case['id']}", headers=self.agent_h).status_code, 403)
        self.assertEqual(self.client.get(self.url, headers=self.agent_h).get_json()['items'], [])
        self.post(f"/{case['id']}/assign", {'assignee_user_id': self.agent, 'expected_version': 1, 'reason': 'test'}, self.agent_h, expected=403)
        other = self.create_organization()['id']
        _, outsider = _register_member(self, other)
        self.grant(outsider, 'case_agent', other)
        self.post(f"/{case['id']}/assign", {'assignee_user_id': outsider, 'expected_version': 1, 'reason': 'test'}, expected=422)
        with self.db.write_transaction() as conn:
            conn.execute('UPDATE users SET is_active=0 WHERE id=?', (self.agent,))
        self.post(f"/{case['id']}/assign", {'assignee_user_id': self.agent, 'expected_version': 1, 'reason': 'test'}, expected=422)
        self.post(f"/{case['id']}/transition", {'status': 'closed', 'expected_version': 1, 'reason': 'test'}, expected=409)

    def test_audit_append_only_validation_and_transaction_rollback(self):
        case = self.create()
        for reason in ['', ' ' * 5, 'x' * 1001]:
            self.post(f"/{case['id']}/assign", {'assignee_user_id': self.agent, 'expected_version': 1, 'reason': reason}, expected=422)
        self.post(f"/{case['id']}/assign", {'assignee_user_id': self.agent, 'expected_version': True, 'reason': 'test'}, expected=422)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.write_transaction() as conn:
                conn.execute("UPDATE organization_operations_events SET reason='rewritten'")
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.write_transaction() as conn:
                conn.execute('DELETE FROM organization_operations_events')
        # Force audit insert failure: case mutation must roll back in the same tx.
        with self.db.write_transaction() as conn:
            conn.execute("CREATE TRIGGER test_fail_audit BEFORE INSERT ON organization_operations_events BEGIN SELECT RAISE(ABORT,'test'); END")
        self.post(f"/{case['id']}/assign", {'assignee_user_id': self.agent, 'expected_version': 1, 'reason': 'test'}, expected=500)
        with self.db.read_transaction() as conn:
            current = dict(conn.execute('SELECT * FROM organization_operations_cases WHERE id=?', (case['id'],)).fetchone())
        self.assertEqual(case, current)

    def test_zero_case_id_is_not_found_for_read_and_mutations(self):
        self.assertEqual(self.client.get(self.url + '/0', headers=self.manager_h).status_code, 404)
        self.post('/0/assign', {'assignee_user_id': self.agent, 'expected_version': 1,
                               'reason': 'test'}, expected=404)
        self.post('/0/transition', {'status': 'sourcing', 'expected_version': 1,
                                   'reason': 'test'}, expected=404)
        with self.db.read_transaction() as conn:
            for table in ['organization_operations_cases', 'organization_operations_events',
                          'organization_operations_idempotency']:
                self.assertEqual(conn.execute(f'SELECT COUNT(*) AS n FROM {table}').fetchone()['n'], 0)
