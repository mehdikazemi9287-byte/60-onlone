"""Isolated new readiness contract tests; no financial execution."""
import sqlite3
import unittest
from types import SimpleNamespace
from flask import Flask
from app.api.v1.organization_finance_policy import bp
from app.core.errors import ApiError
from app.core.security import create_access_token
from tests.test_organization_operations_context import MemoryReadDB

class FinancePolicyTest(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:');self.conn.row_factory=sqlite3.Row;self.addCleanup(self.conn.close)
        self.conn.executescript('''CREATE TABLE users(id INTEGER,email TEXT,role TEXT,is_active INTEGER);
        CREATE TABLE organizations(id INTEGER,status TEXT);
        CREATE TABLE organization_memberships(organization_id INTEGER,user_id INTEGER,role TEXT,status TEXT);
        CREATE TABLE revoked_tokens(jti TEXT,revoked_at TEXT);
        INSERT INTO users VALUES(1,'admin@example.test','customer',1),(2,'finance@example.test','customer',1),(3,'employee@example.test','customer',1),(4,'platform@example.test','admin',1);
        INSERT INTO organizations VALUES(10,'active'),(20,'active');
        INSERT INTO organization_memberships VALUES(10,1,'organization_admin','active'),(10,2,'organization_finance','active'),(10,3,'employee','active');''')
        self.secret='s8-isolated-test-secret-never-runtime-12345678';app=Flask(__name__);app.extensions['db']=MemoryReadDB(self.conn);app.extensions['settings']=SimpleNamespace(secret_key=self.secret,jwt_algorithm='HS256');app.register_blueprint(bp)
        @app.errorhandler(ApiError)
        def error(e):return e.to_dict(),e.status_code
        self.client=app.test_client()
    def get(self,user=1,org=10):
        t=create_access_token(user_id=user,email='test@example.test',role='admin',secret=self.secret,algorithm='HS256',ttl_seconds=60)
        return self.client.get(f'/api/v1/organizations/{org}/payment-policy',headers={'Authorization':'Bearer '+t})
    def test_readiness_disabled_no_side_effects(self):
        before=self.conn.total_changes
        for actor in [1,2]:
            r=self.get(actor);self.assertEqual(r.status_code,200);p=r.json['policy']
            self.assertFalse(p['financial_actions_enabled']);self.assertIsNone(p['policy_version']);self.assertEqual(len(p['matrix']),9)
            self.assertTrue(all(not m['enabled'] for m in p['methods']));self.assertNotIn('balance',p)
        self.assertEqual(self.conn.total_changes,before)
    def test_wrong_tenant_employee_platform_anonymous_denied(self):
        self.assertEqual(self.get(org=20).status_code,403)
        for actor in [3,4]:self.assertEqual(self.get(actor).status_code,403)
        self.assertEqual(self.client.get('/api/v1/organizations/10/payment-policy').status_code,401)
        self.assertEqual(self.client.post('/api/v1/organizations/10/payment-policy',json={'approved':True}).status_code,405)
    def test_revoked_membership_and_inactive_organization(self):
        self.conn.execute("UPDATE organization_memberships SET status='revoked' WHERE user_id=2")
        self.assertEqual(self.get(2).status_code,403)
        self.conn.execute("UPDATE organizations SET status='suspended' WHERE id=10")
        self.assertEqual(self.get(1).status_code,403)
