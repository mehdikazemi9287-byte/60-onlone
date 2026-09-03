from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import ConfigError, load_settings  # noqa: E402


class ConfigTest(unittest.TestCase):
    def test_missing_secret_key_refuses_to_boot(self):
        with mock.patch.dict(os.environ, {"DATABASE_URL": "sqlite:///x.db"}, clear=True):
            with self.assertRaises(ConfigError):
                load_settings()

    def test_blank_secret_key_refuses_to_boot(self):
        env = {"SECRET_KEY": "   ", "DATABASE_URL": "sqlite:///x.db"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigError):
                load_settings()

    def test_missing_database_url_refuses_to_boot(self):
        with mock.patch.dict(os.environ, {"SECRET_KEY": "a" * 40}, clear=True):
            with self.assertRaises(ConfigError):
                load_settings()

    def test_short_secret_key_refuses_to_boot(self):
        env = {"SECRET_KEY": "too-short", "DATABASE_URL": "sqlite:///x.db"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigError):
                load_settings()

    def test_settings_load_from_environment(self):
        secret = "0123456789abcdef0123456789abcdef"
        env = {"SECRET_KEY": secret, "DATABASE_URL": "sqlite:///./data/x.db"}
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.secret_key, secret)
        self.assertEqual(settings.sqlite_path, "./data/x.db")

    def test_non_sqlite_database_url_is_rejected(self):
        env = {"SECRET_KEY": "a" * 40, "DATABASE_URL": "postgresql://u:p@h/db"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigError):
                load_settings().sqlite_path

    def test_no_hardcoded_secret_anywhere_in_source(self):
        """Grep the whole backend package for an assigned SECRET_KEY literal."""
        root = Path(__file__).resolve().parents[1] / "app"
        offenders = []
        for path in root.rglob("*.py"):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "SECRET_KEY" in stripped and ("=" in stripped and '"' in stripped or "'" in stripped):
                    # Allowed: reading it from the environment by name.
                    if "_require(" in stripped or "os.environ" in stripped:
                        continue
                    offenders.append(f"{path.name}:{lineno}: {stripped}")
        self.assertEqual(offenders, [], f"hard-coded secret candidates: {offenders}")


if __name__ == "__main__":
    unittest.main()
