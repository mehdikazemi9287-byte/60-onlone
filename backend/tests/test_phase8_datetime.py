"""Phase 8 — Workstream F: Time and Datetime Correctness.

Verifies that all service modules use timezone-aware UTC datetimes
(datetime.now(timezone.utc)) and not the deprecated datetime.utcnow().
"""
from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path


class TestNoUtcnow(unittest.TestCase):
    """No service or API file may call datetime.utcnow()."""

    _SERVICES_DIR = Path(__file__).parent.parent / "app"

    def test_no_utcnow_in_service_files(self):
        """Scan all .py files under app/ for datetime.utcnow() calls."""
        violations: list[str] = []
        for root, _dirs, files in os.walk(self._SERVICES_DIR):
            for name in files:
                if not name.endswith(".py"):
                    continue
                fpath = Path(root) / name
                source = fpath.read_text(encoding="utf-8")
                if "utcnow()" in source:
                    violations.append(str(fpath.relative_to(self._SERVICES_DIR.parent.parent)))

        self.assertEqual(
            violations,
            [],
            msg=(
                "The following files still use deprecated datetime.utcnow().\n"
                "Replace with datetime.now(timezone.utc) or datetime.now(datetime.timezone.utc):\n"
                + "\n".join(f"  {v}" for v in violations)
            ),
        )

    def test_outbox_worker_uses_timezone_utc(self):
        """The outbox worker must use timezone-aware datetimes."""
        fpath = Path(__file__).parent.parent / "app" / "services" / "outbox_worker.py"
        source = fpath.read_text(encoding="utf-8")
        self.assertNotIn("utcnow()", source)
        self.assertIn("timezone.utc", source)

    def test_security_module_uses_timezone_utc(self):
        """The security (JWT) module must use timezone-aware datetimes."""
        fpath = Path(__file__).parent.parent / "app" / "core" / "security.py"
        if not fpath.exists():
            self.skipTest("security.py not found")
        source = fpath.read_text(encoding="utf-8")
        self.assertNotIn("utcnow()", source)


if __name__ == "__main__":
    unittest.main()
