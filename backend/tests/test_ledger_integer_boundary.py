"""Isolated synthetic ledger boundaries; never opens a business database."""
import sqlite3
import unittest
from decimal import Decimal
from app.services.ledger_service import Entry, post_transaction, ACCOUNT_PSP_CLEARING, ACCOUNT_SALES_REVENUE
from app.core.errors import ValidationError

class NoSQL:
    def execute(self, *args, **kwargs):
        raise AssertionError('Invalid amount reached database writes')

class LedgerIntegerBoundary(unittest.TestCase):
    def post(self, amount, conn=None):
        return post_transaction(conn or NoSQL(), reference='TEST-ONLY', description='[TEST ONLY]',
            entries=[Entry(ACCOUNT_PSP_CLEARING,'debit',amount), Entry(ACCOUNT_SALES_REVENUE,'credit',amount)])

    def test_noninteger_values_never_reach_sql(self):
        for amount in (True, False, 1.0, 0.5, Decimal('1'), '100', None, float('nan'), float('inf')):
            with self.subTest(amount=repr(amount)):
                with self.assertRaises(ValidationError): self.post(amount)

    def test_nonpositive_values_never_reach_sql(self):
        for amount in (0,-1):
            with self.assertRaises(ValidationError): self.post(amount)

    def test_database_overflow_is_controlled_before_sql(self):
        with self.assertRaises(ValidationError): self.post(1<<63)

    def test_unbalanced_entries_never_reach_sql(self):
        with self.assertRaises(ValidationError):
            post_transaction(NoSQL(),reference='TEST-ONLY',description='[TEST ONLY]',entries=[
                Entry(ACCOUNT_PSP_CLEARING,'debit',100),Entry(ACCOUNT_SALES_REVENUE,'credit',99)])

    def test_aggregate_overflow_never_reaches_sql(self):
        with self.assertRaises(ValidationError):
            post_transaction(NoSQL(),reference='TEST-ONLY',description='[TEST ONLY]',entries=[
                Entry(ACCOUNT_PSP_CLEARING,'debit',1<<62),Entry(ACCOUNT_PSP_CLEARING,'debit',1<<62),
                Entry(ACCOUNT_SALES_REVENUE,'credit',1<<62),Entry(ACCOUNT_SALES_REVENUE,'credit',1<<62)])

    def test_valid_integer_is_preserved_exactly(self):
        conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
        self.addCleanup(conn.close)
        conn.executescript('''CREATE TABLE ledger_accounts(id INTEGER PRIMARY KEY,code TEXT UNIQUE,name_fa TEXT,type TEXT);
        CREATE TABLE ledger_transactions(id INTEGER PRIMARY KEY,reference TEXT UNIQUE,description TEXT);
        CREATE TABLE ledger_entries(transaction_id INTEGER,account_id INTEGER,direction TEXT,amount_minor INTEGER,currency TEXT);''')
        self.assertEqual(self.post(123456789,conn),1)
        rows=conn.execute('SELECT amount_minor,typeof(amount_minor) t FROM ledger_entries').fetchall()
        self.assertEqual([(r['amount_minor'],r['t']) for r in rows],[(123456789,'integer')]*2)

if __name__=='__main__': unittest.main()
