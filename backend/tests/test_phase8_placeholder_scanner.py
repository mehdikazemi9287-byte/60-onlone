"""Phase 8 — Issue 2: Safe PostgreSQL placeholder conversion tests.

Tests that _adapt_sql correctly handles every context where a ``?``
character MUST NOT be converted to ``%s``:
  - Single-quoted string literals (including escaped '' pairs)
  - Double-quoted identifiers
  - Line comments (--)
  - Block comments (/* */, nested /* /* */ */)
  - Dollar-quoted strings ($$ ... $$, $tag$ ... $tag$)
  - JSON and URL values stored in single-quoted strings
  - Placeholder count validation against parameter list

Also verifies that bare ``%`` characters are doubled to ``%%`` (required
by psycopg2) and that the adapted SQL is semantically correct for
positional binding.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import _adapt_sql


class TestAdaptSqlBasic(unittest.TestCase):
    """Basic placeholder replacement — happy-path cases."""

    def test_single_placeholder(self):
        result = _adapt_sql("SELECT * FROM t WHERE id = ?")
        self.assertEqual(result, "SELECT * FROM t WHERE id = %s")

    def test_multiple_placeholders(self):
        result = _adapt_sql("INSERT INTO t (a, b, c) VALUES (?, ?, ?)")
        self.assertEqual(result, "INSERT INTO t (a, b, c) VALUES (%s, %s, %s)")

    def test_no_placeholder(self):
        sql = "SELECT 1"
        self.assertEqual(_adapt_sql(sql), "SELECT 1")

    def test_empty_string(self):
        self.assertEqual(_adapt_sql(""), "")

    def test_whitespace_only(self):
        self.assertEqual(_adapt_sql("   "), "   ")


class TestAdaptSqlSingleQuotedStrings(unittest.TestCase):
    """? inside single-quoted string literals must NOT be converted."""

    def test_question_mark_inside_literal(self):
        sql = "SELECT * FROM t WHERE url = 'http://x.com?q=1' AND id = ?"
        result = _adapt_sql(sql)
        self.assertIn("'http://x.com?q=1'", result)  # literal preserved (? inside stays as ?)
        self.assertIn("%s", result)                    # real placeholder converted
        self.assertEqual(result.count("%s"), 1)
        # The ? inside the string literal is correctly preserved (not a placeholder),
        # so the adapted result still contains exactly one ? character.
        self.assertEqual(result.count("?"), 1)

    def test_question_mark_in_json_literal(self):
        sql = "INSERT INTO t (data) VALUES ('{\"key\":\"val?\"}') WHERE 1=?"
        result = _adapt_sql(sql)
        # The ? inside the JSON string literal is preserved
        self.assertIn("'", result)
        self.assertEqual(result.count("%s"), 1)

    def test_escaped_single_quote_in_literal(self):
        """Escaped '' inside a string must not confuse the scanner."""
        sql = "SELECT * FROM t WHERE name = 'don''t?' AND id = ?"
        result = _adapt_sql(sql)
        self.assertIn("'don''t?'", result)   # literal intact
        self.assertEqual(result.count("%s"), 1)

    def test_empty_string_literal(self):
        sql = "UPDATE t SET col = '' WHERE id = ?"
        result = _adapt_sql(sql)
        self.assertIn("''", result)
        self.assertEqual(result.count("%s"), 1)

    def test_multiple_literals_and_placeholders(self):
        sql = "SELECT * FROM t WHERE a='x?y' AND b=? AND c='??' AND d=?"
        result = _adapt_sql(sql)
        self.assertEqual(result.count("%s"), 2)
        # String literals preserved
        self.assertIn("'x?y'", result)
        self.assertIn("'??'", result)


class TestAdaptSqlDoubleQuotedIdentifiers(unittest.TestCase):
    """? inside double-quoted identifiers must NOT be converted."""

    def test_question_mark_in_identifier(self):
        sql = 'SELECT "col?name" FROM t WHERE id = ?'
        result = _adapt_sql(sql)
        self.assertIn('"col?name"', result)
        self.assertEqual(result.count("%s"), 1)

    def test_escaped_double_quote_in_identifier(self):
        sql = 'SELECT "col""?x" FROM t WHERE id = ?'
        result = _adapt_sql(sql)
        self.assertIn('"col""?x"', result)
        self.assertEqual(result.count("%s"), 1)


class TestAdaptSqlLineComments(unittest.TestCase):
    """? on a line comment must NOT be converted."""

    def test_question_mark_in_line_comment(self):
        sql = "SELECT id -- what is this?\nFROM t WHERE id = ?"
        result = _adapt_sql(sql)
        self.assertIn("-- what is this?", result)
        self.assertEqual(result.count("%s"), 1)

    def test_entire_line_is_comment(self):
        sql = "-- SELECT ? FROM t\nSELECT id FROM t WHERE id = ?"
        result = _adapt_sql(sql)
        self.assertIn("-- SELECT ? FROM t", result)
        self.assertEqual(result.count("%s"), 1)

    def test_comment_at_end_of_file(self):
        sql = "SELECT 1 -- trailing ? comment"
        result = _adapt_sql(sql)
        self.assertIn("-- trailing ? comment", result)
        self.assertEqual(result.count("%s"), 0)


class TestAdaptSqlBlockComments(unittest.TestCase):
    """? inside /* ... */ block comments must NOT be converted."""

    def test_question_mark_in_block_comment(self):
        sql = "SELECT /* what? */ id FROM t WHERE id = ?"
        result = _adapt_sql(sql)
        self.assertIn("/* what? */", result)
        self.assertEqual(result.count("%s"), 1)

    def test_nested_block_comment(self):
        """PostgreSQL supports nested block comments; scanner must handle them."""
        sql = "SELECT /* outer /* inner ? */ still_outer ? */ id FROM t WHERE id = ?"
        result = _adapt_sql(sql)
        # All ? inside the (nested) comment must be preserved
        self.assertEqual(result.count("%s"), 1)

    def test_multi_line_block_comment(self):
        sql = "/* line1\n? line2\n */ SELECT id FROM t WHERE id = ?"
        result = _adapt_sql(sql)
        self.assertEqual(result.count("%s"), 1)

    def test_block_comment_only(self):
        sql = "/* SELECT ? FROM t */"
        result = _adapt_sql(sql)
        self.assertIn("?", result)
        self.assertEqual(result.count("%s"), 0)


class TestAdaptSqlDollarQuoting(unittest.TestCase):
    """? inside dollar-quoted strings must NOT be converted."""

    def test_question_mark_in_dollar_quote(self):
        sql = "DO $$ BEGIN RAISE NOTICE 'val?'; END $$; SELECT id FROM t WHERE id = ?"
        result = _adapt_sql(sql)
        self.assertIn("$$", result)
        self.assertEqual(result.count("%s"), 1)

    def test_tagged_dollar_quote(self):
        sql = "DO $body$ BEGIN RAISE NOTICE 'val?'; END $body$; UPDATE t SET x=? WHERE id=?"
        result = _adapt_sql(sql)
        self.assertIn("$body$", result)
        self.assertEqual(result.count("%s"), 2)

    def test_dollar_quote_with_inner_question_marks(self):
        sql = "SELECT $$ SELECT ? FROM dual $$ AS q WHERE id = ?"
        result = _adapt_sql(sql)
        self.assertIn("$$", result)
        self.assertEqual(result.count("%s"), 1)


class TestAdaptSqlPercentEscaping(unittest.TestCase):
    """Bare % outside placeholders must be doubled for psycopg2."""

    def test_bare_percent_doubled(self):
        sql = "SELECT col FROM t WHERE col LIKE '%foo%' AND id = ?"
        result = _adapt_sql(sql)
        # The % in the LIKE pattern must be doubled: %%foo%%
        self.assertIn("%%foo%%", result)
        self.assertEqual(result.count("%s"), 1)

    def test_no_bare_percent(self):
        sql = "SELECT id FROM t WHERE id = ?"
        result = _adapt_sql(sql)
        self.assertEqual(result, "SELECT id FROM t WHERE id = %s")


class TestAdaptSqlCountValidation(unittest.TestCase):
    """Placeholder count must be validated against the params list."""

    def test_exact_match_passes(self):
        sql = "INSERT INTO t (a, b) VALUES (?, ?)"
        result = _adapt_sql(sql, params=["x", "y"])
        self.assertEqual(result, "INSERT INTO t (a, b) VALUES (%s, %s)")

    def test_too_few_params_raises(self):
        sql = "INSERT INTO t (a, b) VALUES (?, ?)"
        with self.assertRaises(ValueError) as ctx:
            _adapt_sql(sql, params=["x"])
        self.assertIn("mismatch", str(ctx.exception).lower())

    def test_too_many_params_raises(self):
        sql = "SELECT * FROM t WHERE id = ?"
        with self.assertRaises(ValueError) as ctx:
            _adapt_sql(sql, params=[1, 2])
        self.assertIn("mismatch", str(ctx.exception).lower())

    def test_zero_placeholders_zero_params_passes(self):
        result = _adapt_sql("SELECT 1", params=[])
        self.assertEqual(result, "SELECT 1")

    def test_zero_placeholders_nonzero_params_raises(self):
        with self.assertRaises(ValueError):
            _adapt_sql("SELECT 1", params=["extra"])

    def test_none_params_skips_validation(self):
        """When params=None, no count check is performed."""
        # This should NOT raise even though the counts differ
        result = _adapt_sql("SELECT * FROM t WHERE id = ?", params=None)
        self.assertEqual(result, "SELECT * FROM t WHERE id = %s")


class TestAdaptSqlEdgeCases(unittest.TestCase):
    """Edge cases and pathological inputs."""

    def test_question_mark_only(self):
        result = _adapt_sql("?")
        self.assertEqual(result, "%s")

    def test_adjacent_placeholders(self):
        result = _adapt_sql("? ? ?")
        self.assertEqual(result, "%s %s %s")

    def test_no_context_contamination_across_statements(self):
        """State must reset: single-quote opened and closed before next ?."""
        sql = "SELECT 'hello' FROM t WHERE id = ?"
        result = _adapt_sql(sql)
        self.assertEqual(result.count("%s"), 1)

    def test_comment_then_placeholder(self):
        sql = "-- ignore this ?\nSELECT id FROM t WHERE id = ?"
        result = _adapt_sql(sql)
        self.assertEqual(result.count("%s"), 1)

    def test_url_in_literal(self):
        """URL with ? inside a string literal must not be converted."""
        sql = "INSERT INTO audit (url) VALUES ('https://api.example.com/v1/endpoint?token=abc&page=1') "
        sql += "WHERE org_id = ?"
        result = _adapt_sql(sql)
        self.assertIn("'https://api.example.com/v1/endpoint?token=abc&page=1'", result)
        self.assertEqual(result.count("%s"), 1)

    def test_multiline_sql(self):
        sql = """
            SELECT
                u.id,
                u.email,
                o.name -- org? not a placeholder
            FROM users u
            JOIN organizations o ON o.id = ?
            WHERE u.id = ?
              AND u.status = 'active?no'
        """
        result = _adapt_sql(sql)
        self.assertEqual(result.count("%s"), 2)
        self.assertIn("-- org? not a placeholder", result)
        self.assertIn("'active?no'", result)


if __name__ == "__main__":
    unittest.main()
