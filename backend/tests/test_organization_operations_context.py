"""New read-context regressions only; synthetic in-memory schema, no migrations."""
import json
import sqlite3
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from flask import Flask
from app.api.v1.organization_operations import bp
from app.core.errors import ApiError
from app.core.security import create_access_token


class MemoryReadDB:
    def __init__(self, conn):
        self.conn = conn

    def query_one(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()

    @contextmanager
    def read_transaction(self):
        yield self.conn


class OperationsContextTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.executescript('''
        CREATE TABLE users(id INTEGER,email TEXT,role TEXT,is_active INTEGER);
        CREATE TABLE organizations(id INTEGER,display_name TEXT,status TEXT);
        CREATE TABLE organization_operations_grants(organization_id INTEGER,user_id INTEGER,capability TEXT,status TEXT);
        CREATE TABLE organization_operations_cases(id INTEGER,organization_id INTEGER,purchase_request_id INTEGER,assignee_user_id INTEGER,status TEXT,version INTEGER);
        CREATE TABLE organization_operations_events(id INTEGER,case_id INTEGER,actor_user_id INTEGER,action TEXT,reason TEXT,created_at TEXT);
        CREATE TABLE purchase_requests(id INTEGER,organization_id INTEGER,request_number TEXT,title TEXT,status TEXT,needed_by_date TEXT,substitution_policy TEXT,destinations_json TEXT);
        CREATE TABLE purchase_request_items(id INTEGER,purchase_request_id INTEGER,master_product_id INTEGER,free_text_description TEXT,quantity INTEGER,unit TEXT,notes TEXT);
        CREATE TABLE revoked_tokens(jti TEXT,revoked_at TEXT);
        INSERT INTO users VALUES(1,'manager@example.test','customer',1),(2,'agent@example.test','customer',1),(3,'admin@example.test','admin',1);
        INSERT INTO organizations VALUES(1,'[TEST ONLY] A','active'),(2,'[TEST ONLY] B','active');
        INSERT INTO organization_operations_grants VALUES(1,1,'case_manager','active'),(1,2,'case_agent','active');
        INSERT INTO purchase_requests VALUES(10,1,'TEST-A','[TEST ONLY] need','submitted',NULL,'require_approval','[]'),(20,2,'TEST-B','[TEST ONLY] private', 'submitted',NULL,'disallow','[]');
        INSERT INTO purchase_request_items VALUES(1,10,NULL,'[TEST ONLY] free text',2,'عدد','specification');
        INSERT INTO organization_operations_cases VALUES(100,1,10,2,'triage',1),(200,1,10,1,'triage',1);
        INSERT INTO organization_operations_events VALUES(1,100,1,'assign','[TEST ONLY] assignment','2026-09-25T00:00:00Z');
        ''')
        destinations = [{'province':'[TEST]','city':'[TEST]','address':'[TEST ONLY]',
                         'allocations':[{'item_index':0,'quantity':2}]}]
        self.conn.execute('UPDATE purchase_requests SET destinations_json=? WHERE id=10', (json.dumps(destinations),))
        self.secret = 'isolated-context-test-secret-not-runtime-123456'
        app = Flask(__name__)
        app.extensions['db'] = MemoryReadDB(self.conn)
        app.extensions['settings'] = SimpleNamespace(secret_key=self.secret,jwt_algorithm='HS256')
        app.register_blueprint(bp)
        @app.errorhandler(ApiError)
        def error(exc):
            return exc.to_dict(), exc.status_code
        self.client = app.test_client()
        self.path = '/api/v1/internal/organizations'

    def headers(self, uid):
        token = create_access_token(user_id=uid,email='synthetic@example.test',role='admin',secret=self.secret,algorithm='HS256',ttl_seconds=60)
        return {'Authorization':'Bearer '+token}

    def get(self, tail='', uid=1):
        return self.client.get(self.path+tail,headers=self.headers(uid))

    def test_discovery_requires_actual_mandate_not_token_or_platform_admin(self):
        self.assertEqual(self.client.get(self.path).status_code,401)
        self.assertEqual(self.get(uid=3).get_json(),{'items':[]})
        self.assertEqual(self.get(uid=2).get_json(),{'items':[{'id':1,'display_name':'[TEST ONLY] A','capabilities':['case_agent']}]})
        self.conn.execute("INSERT INTO organization_operations_grants VALUES(1,2,'case_manager','active')")
        data=self.get(uid=2).get_json()['items']
        self.assertEqual(len(data),1)
        self.assertEqual(data[0]['capabilities'],['case_agent','case_manager'])

    def test_assigned_context_is_persisted_and_read_does_not_change_audit(self):
        before=self.conn.total_changes
        response=self.get('/1/cases/100',2)
        self.assertEqual(response.status_code,200)
        case=response.get_json()['case']
        self.assertEqual(case['purchase_request']['items'][0]['quantity'],2)
        self.assertEqual(case['purchase_request']['destinations'][0]['allocations'][0]['quantity'],2)
        self.assertEqual(case['events'][0]['reason'],'[TEST ONLY] assignment')
        self.assertEqual(self.conn.total_changes,before)
        self.assertEqual(self.get('/1/cases/200',2).status_code,403)
        self.assertEqual(self.get('/2/cases/100',2).status_code,403)

    def test_broken_cross_organization_reference_never_leaks_request(self):
        self.conn.execute('UPDATE organization_operations_cases SET purchase_request_id=20 WHERE id=100')
        r=self.get('/1/cases/100')
        self.assertEqual(r.status_code,404)
        self.assertNotIn('private',r.get_data(as_text=True))

    def test_revoked_grant_and_inactive_org_remove_discovery_and_context(self):
        self.conn.execute("UPDATE organization_operations_grants SET status='revoked' WHERE user_id=2")
        self.assertEqual(self.get(uid=2).get_json(),{'items':[]})
        self.assertEqual(self.get('/1/cases/100',2).status_code,403)
        self.conn.execute("UPDATE organizations SET status='suspended' WHERE id=1")
        self.assertEqual(self.get().get_json(),{'items':[]})
        self.assertEqual(self.get('/1/cases/100').status_code,403)

    def test_inactive_user_cannot_discover(self):
        self.conn.execute('UPDATE users SET is_active=0 WHERE id=1')
        self.assertEqual(self.get().status_code,401)
