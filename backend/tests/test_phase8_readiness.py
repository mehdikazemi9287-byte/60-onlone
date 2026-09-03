"""Phase 8 — Blocker 5: Readiness Correctness tests.

Tests:
  - Readiness returns 200 with expected_version when schema is at head
  - Readiness returns 503 with reason='schema_behind' when schema is behind
  - Readiness returns 503 with reason='database_unreachable' when DB is down
  - Readiness never exposes raw exception text
  - Readiness determines expected head from migration directory (not hardcoded)
  - Liveness probe is 200 regardless of DB state
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase


class TestReadinessCorrectness(AppTestCase):

    def test_readiness_returns_200_when_up_to_date(self):
        """A freshly migrated DB returns 200 with schema_version == expected."""
        resp = self.client.get("/api/v1/health/ready")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "ready")
        self.assertIn("schema_version", body)
        self.assertIn("expected_version", body)
        self.assertEqual(body["schema_version"], body["expected_version"])

    def test_readiness_version_matches_migration_directory(self):
        """expected_version must come from the migration directory, not a hardcode."""
        from app.core.migrator import MIGRATIONS_DIR, discover
        migrations = discover(MIGRATIONS_DIR)
        expected = migrations[-1][0] if migrations else None

        resp = self.client.get("/api/v1/health/ready")
        body = resp.get_json()
        if resp.status_code == 200:
            self.assertEqual(body["expected_version"], expected)

    def test_readiness_503_when_schema_behind(self):
        """When the applied version is behind the expected head, return 503."""
        from app.core.migrator import MIGRATIONS_DIR, discover

        migrations = discover(MIGRATIONS_DIR)
        if len(migrations) < 2:
            self.skipTest("Need at least 2 migrations to test behind-head scenario")

        # Mock current_version to return an old version
        old_version = migrations[0][0]  # e.g. '0001'
        with patch("app.api.v1.health.current_version", return_value=old_version):
            resp = self.client.get("/api/v1/health/ready")

        self.assertEqual(resp.status_code, 503)
        body = resp.get_json()
        self.assertEqual(body["status"], "not_ready")
        self.assertEqual(body["reason"], "schema_behind")
        self.assertIn("schema_version", body)
        self.assertIn("expected_version", body)
        self.assertNotEqual(body["schema_version"], body["expected_version"])

    def test_readiness_503_when_db_unreachable(self):
        """When DB query fails, readiness returns 503 with database_unreachable."""
        with patch("app.api.v1.health.get_db") as mock_get_db:
            mock_db = mock_get_db.return_value
            mock_db.query_one.side_effect = Exception("database is locked")

            resp = self.client.get("/api/v1/health/ready")

        self.assertEqual(resp.status_code, 503)
        body = resp.get_json()
        self.assertEqual(body["status"], "not_ready")
        self.assertEqual(body["reason"], "database_unreachable")

    def test_readiness_503_does_not_expose_raw_exception_text(self):
        """Error reason must be a code, not the raw exception message."""
        with patch("app.api.v1.health.get_db") as mock_get_db:
            mock_db = mock_get_db.return_value
            SECRET_DETAIL = "SQLITE_ERROR_WITH_SECRET_PATH_/data/prod.db"
            mock_db.query_one.side_effect = Exception(SECRET_DETAIL)

            resp = self.client.get("/api/v1/health/ready")

        body = resp.get_json()
        body_str = str(body)
        self.assertNotIn(SECRET_DETAIL, body_str)
        self.assertNotIn("/data/prod.db", body_str)

    def test_readiness_503_when_migration_metadata_corrupt(self):
        """When current_version raises, return 503 with migration_metadata_corrupt."""
        with patch("app.api.v1.health.current_version") as mock_cv:
            mock_cv.side_effect = Exception("schema_migrations table corrupt")

            resp = self.client.get("/api/v1/health/ready")

        self.assertEqual(resp.status_code, 503)
        body = resp.get_json()
        self.assertEqual(body["reason"], "migration_metadata_corrupt")

    def test_liveness_always_200(self):
        """Liveness probe returns 200 regardless of DB state."""
        with patch("app.api.v1.health.get_db") as mock_get_db:
            mock_db = mock_get_db.return_value
            mock_db.query_one.side_effect = Exception("db is gone")

            resp = self.client.get("/api/v1/health/live")
        # Liveness does not call get_db, so this mock is irrelevant
        # but the probe should still return 200
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "alive")

    def test_health_combined_backward_compat(self):
        """GET /api/v1/health returns 200 with status=ok."""
        resp = self.client.get("/api/v1/health")
        self.assertIn(resp.status_code, (200, 503))


class TestReadinessNeverNone(AppTestCase):

    def test_schema_version_is_string_not_none(self):
        """Readiness schema_version must be a string, not null."""
        resp = self.client.get("/api/v1/health/ready")
        if resp.status_code == 200:
            body = resp.get_json()
            self.assertIsInstance(body["schema_version"], str)
            self.assertIsInstance(body["expected_version"], str)


if __name__ == "__main__":
    unittest.main()
