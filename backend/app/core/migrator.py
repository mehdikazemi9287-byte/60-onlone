"""Forward-only SQL migration runner — SQLite and PostgreSQL.

Backend dispatch:
  SQLite   — each migration runs inside sqlite3's executescript() with an
             embedded BEGIN/COMMIT, making the DDL and the schema_migrations
             bookkeeping row atomic.
  PostgreSQL — native PostgreSQL SQL files from migrations_postgresql/ are
             executed statement-by-statement using a proper parser that handles
             dollar-quoted strings ($$...$$), quoted identifiers, and SQL
             comments without splitting on semicolons inside string literals.
             Each migration + bookkeeping INSERT commit in one transaction.

Migration directories:
  SQLite:     backend/migrations/          (SQLite-specific syntax)
  PostgreSQL: backend/migrations_postgresql/  (PostgreSQL-native syntax)
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from app.core.db import DatabaseBackend

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
MIGRATIONS_PG_DIR = Path(__file__).resolve().parents[2] / "migrations_postgresql"

_NAME_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

# Compatible with both SQLite and PostgreSQL: no DEFAULT that uses
# database-specific functions; applied_at is always supplied explicitly.
BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    checksum   TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""


class MigrationError(RuntimeError):
    pass


def _is_postgres(db: DatabaseBackend) -> bool:
    from app.core.db import PostgreSQLBackend
    return isinstance(db, PostgreSQLBackend)


def _migrations_dir(db: DatabaseBackend) -> Path:
    """Return the appropriate migrations directory for the given backend."""
    if _is_postgres(db):
        return MIGRATIONS_PG_DIR
    return MIGRATIONS_DIR


def discover(directory: Path | None = None, db: DatabaseBackend | None = None) -> list[tuple[str, str, Path]]:
    """Discover migration files in the appropriate directory.

    If directory is given, use it directly.
    If db is given, pick the right directory for the backend.
    Falls back to SQLite migrations directory.
    """
    if directory is None:
        if db is not None:
            directory = _migrations_dir(db)
        else:
            directory = MIGRATIONS_DIR
    found = []
    for path in sorted(directory.glob("*.sql")):
        match = _NAME_RE.match(path.name)
        if not match:
            raise MigrationError(f"Bad migration filename: {path.name}")
        found.append((match.group(1), match.group(2), path))
    return found


def _ensure_migration_table(db: DatabaseBackend) -> None:
    """Create the schema_migrations tracking table if it does not exist."""
    if _is_postgres(db):
        conn = db.connection
        try:
            with conn.cursor() as cur:
                cur.execute(BOOTSTRAP)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
    else:
        db.execute(BOOTSTRAP)


def applied_versions(db: DatabaseBackend) -> set[str]:
    _ensure_migration_table(db)
    return {row["version"] for row in db.query("SELECT version FROM schema_migrations")}


def _split_pg_statements(sql: str) -> list[str]:
    """Split a PostgreSQL SQL script into individual statements.

    Handles:
    - Dollar-quoted strings ($$...$$, $tag$...$tag$)
    - Single-quoted string literals (with escape sequences)
    - Standard SQL comments (-- line comments)
    - Block comments (/* ... */)
    - Nested block comments (PostgreSQL supports them)

    This is far safer than naive sql.split(";") which breaks on semicolons
    inside string literals, dollar-quoted function bodies, and comments.
    """
    statements: list[str] = []
    current: list[str] = []
    i = 0
    n = len(sql)

    in_dollar_quote: str | None = None   # the dollar-quote tag, e.g. "$$" or "$fn$"
    in_single_quote = False
    block_comment_depth = 0

    while i < n:
        ch = sql[i]

        # ── Block comment ─────────────────────────────────────────────────────
        if not in_dollar_quote and not in_single_quote and block_comment_depth == 0:
            if sql[i:i+2] == "/*":
                block_comment_depth += 1
                current.append(sql[i:i+2])
                i += 2
                continue

        if block_comment_depth > 0:
            if sql[i:i+2] == "/*":
                block_comment_depth += 1
                current.append(sql[i:i+2])
                i += 2
                continue
            elif sql[i:i+2] == "*/":
                block_comment_depth -= 1
                current.append(sql[i:i+2])
                i += 2
                continue
            else:
                current.append(ch)
                i += 1
                continue

        # ── Line comment ──────────────────────────────────────────────────────
        if not in_dollar_quote and not in_single_quote and sql[i:i+2] == "--":
            # consume to end of line
            end = sql.find("\n", i)
            if end == -1:
                current.append(sql[i:])
                i = n
            else:
                current.append(sql[i:end+1])
                i = end + 1
            continue

        # ── Dollar quoting ────────────────────────────────────────────────────
        if not in_single_quote and block_comment_depth == 0:
            # Try to match a dollar-quote tag: $tag$ or $$
            dq_match = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$", sql[i:])
            if dq_match:
                tag = dq_match.group(0)  # e.g. "$$" or "$body$"
                if in_dollar_quote is None:
                    # Opening
                    in_dollar_quote = tag
                    current.append(tag)
                    i += len(tag)
                    continue
                elif in_dollar_quote == tag:
                    # Closing
                    in_dollar_quote = None
                    current.append(tag)
                    i += len(tag)
                    continue

        # ── Single-quoted string ───────────────────────────────────────────────
        if not in_dollar_quote and block_comment_depth == 0:
            if not in_single_quote and ch == "'":
                in_single_quote = True
                current.append(ch)
                i += 1
                continue
            elif in_single_quote:
                if ch == "'" and i + 1 < n and sql[i+1] == "'":
                    # Escaped quote ''
                    current.append("''")
                    i += 2
                    continue
                elif ch == "'":
                    in_single_quote = False
                    current.append(ch)
                    i += 1
                    continue

        # ── Statement terminator ───────────────────────────────────────────────
        if ch == ";" and not in_dollar_quote and not in_single_quote and block_comment_depth == 0:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    # Any remaining content (no trailing semicolon)
    remainder = "".join(current).strip()
    if remainder:
        statements.append(remainder)

    return statements


def _apply_migration_sqlite(
    db: DatabaseBackend,
    sql: str,
    version: str,
    name: str,
    checksum: str,
    now: str,
) -> None:
    """Apply one migration on SQLite using executescript() with BEGIN/COMMIT."""
    conn = db.connection
    if version == '0043' and name == 'nullable_master_unit_pack':
        from app.core import catalog_nullable_migration
        expected = re.search(r"implementation-sha256: ([a-f0-9]{64})", sql)
        actual = hashlib.sha256(Path(catalog_nullable_migration.__file__).read_bytes()).hexdigest()
        if expected is None or actual != expected.group(1):
            raise MigrationError("Nullable migration implementation digest mismatch")
        catalog_nullable_migration.apply(conn, checksum=checksum, now=now)
        return
    script = (
        "BEGIN;\n"
        f"{sql}\n"
        "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
        f"VALUES ('{version}', '{name}', '{checksum}', '{now}');\n"
        "COMMIT;\n"
    )
    try:
        conn.executescript(script)
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def _apply_migration_pg(
    db: DatabaseBackend,
    sql: str,
    version: str,
    name: str,
    checksum: str,
    now: str,
) -> None:
    """Apply one PostgreSQL-native migration.

    Uses a proper SQL statement splitter that handles dollar-quoted strings,
    single-quoted literals, and comments — not naive split(";").

    All statements + the schema_migrations INSERT commit in one transaction.
    """
    pg_conn = db.connection
    try:
        with pg_conn.cursor() as cur:
            for stmt in _split_pg_statements(sql):
                upper = stmt.strip().upper()
                # Skip embedded transaction-control statements (migration artefacts).
                if upper in ("BEGIN", "BEGIN IMMEDIATE", "COMMIT", "ROLLBACK"):
                    continue
                cur.execute(stmt)

            # Bookkeeping INSERT
            cur.execute(
                "INSERT INTO schema_migrations"
                " (version, name, checksum, applied_at) VALUES (%s, %s, %s, %s)",
                (version, name, checksum, now),
            )
        pg_conn.commit()
    except Exception:
        try:
            pg_conn.rollback()
        except Exception:
            pass
        raise


def upgrade(db: DatabaseBackend, directory: Path | None = None) -> list[str]:
    """Apply every pending migration. Returns the versions applied.

    Uses migrations_postgresql/ for PostgreSQL and migrations/ for SQLite.
    """
    if directory is None:
        directory = _migrations_dir(db)
    done = applied_versions(db)
    newly_applied: list[str] = []
    for version, name, path in discover(directory=directory):
        if version in done:
            continue
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()

        if _is_postgres(db):
            _apply_migration_pg(db, sql, version, name, checksum, now)
        else:
            _apply_migration_sqlite(db, sql, version, name, checksum, now)

        newly_applied.append(version)
    return newly_applied


def current_version(db: DatabaseBackend) -> str | None:
    _ensure_migration_table(db)
    row = db.query_one(
        "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
    )
    return row["version"] if row else None
