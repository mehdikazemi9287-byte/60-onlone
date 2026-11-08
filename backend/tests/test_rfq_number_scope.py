"""Synthetic in-memory allocator fixtures, never runtime business data."""
import datetime,sqlite3,unittest
from app.services.rfq_service import _next_rfq_number
class RfqNumberScopeTest(unittest.TestCase):
 def test_global_sequence_preserves_gaps_and_org_scope(self):
  conn=sqlite3.connect(':memory:');conn.execute('CREATE TABLE rfqs(rfq_number TEXT UNIQUE,organization_id INTEGER)')
  prefix='RFQ-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d')+'-'
  conn.executemany('INSERT INTO rfqs VALUES(?,?)',[(prefix+'0001',101),(prefix+'0008',102)])
  number=_next_rfq_number(conn,999);self.assertEqual(number,prefix+'0009');conn.execute('INSERT INTO rfqs VALUES(?,?)',(number,999));self.assertEqual(_next_rfq_number(conn,101),prefix+'0010');conn.close()
