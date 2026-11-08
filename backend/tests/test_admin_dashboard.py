"""Meaningful authorization, day-boundary and exact-record counting checks; isolated fixtures."""
from datetime import datetime, timezone
from tests.base import AppTestCase
from app.api.v1.admin_dashboard import day_bounds, snapshot
from app.core.errors import ValidationError

class DashboardTests(AppTestCase):
 def test_anonymous_is_denied(self):
  self.assertEqual(self.client.get('/api/v1/admin/dashboard').status_code,401)
 def test_customer_is_denied(self):
  _,h=self.new_customer()
  self.assertEqual(self.client.get('/api/v1/admin/dashboard',headers=h).status_code,403)
 def test_admin_receives_numeric_counts_and_explicit_scope(self):
  r=self.client.get('/api/v1/admin/dashboard?timezone=Asia/Tehran',headers=self.admin_headers())
  self.assertEqual(r.status_code,200,r.get_json())
  d=r.get_json();self.assertEqual(d['timezone'],'Asia/Tehran')
  self.assertTrue(all(type(v) is int and v>=0 for v in d['metrics'].values()))
  self.assertEqual(d['operations']['scope_count'],0)
  self.assertEqual(d['environment'],'test')
 def test_invalid_timezone_is_validation_error(self):
  self.assertEqual(self.client.get('/api/v1/admin/dashboard?timezone=../invalid',headers=self.admin_headers()).status_code,422)
 def test_day_window_is_half_open_and_handles_dst(self):
  start,end=day_bounds('America/New_York',datetime(2026,3,8,15,tzinfo=timezone.utc))
  self.assertEqual((end-start).total_seconds(),23*3600)
  self.assertEqual(start.hour,5);self.assertEqual(end.hour,4)
  with self.assertRaises(ValidationError):day_bounds('not/a/timezone')
 def test_day_count_comes_from_records_and_excludes_end_boundary(self):
  email,password,r=self.register(full_name='[TEST ONLY] count fixture');uid=r.get_json()['user']['id']
  now=datetime(2026,10,10,12,tzinfo=timezone.utc)
  with self.db.write_transaction() as c:
   before=snapshot(c,uid,'UTC',now)['metrics']['personal_today']
   for stamp in ['2026-10-10T00:00:00+00:00','2026-10-10T23:59:59+00:00','2026-10-11T00:00:00+00:00']:
    c.execute("INSERT INTO customer_requests(user_id,kind,subject,message,items_json,idempotency_key,payload_hash,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'open',?,?)",(uid,'procurement','[TEST ONLY] request','[TEST ONLY]','[]','TEST ONLY '+stamp,'TEST ONLY hash',stamp,stamp))
   after=snapshot(c,uid,'UTC',now)['metrics']['personal_today']
  self.assertEqual(after,before+2)
