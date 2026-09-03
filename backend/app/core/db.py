"""Database access with explicit transaction boundaries.

Architecture: DatabaseBackend ABC + SQLiteBackend + PostgreSQLBackend.

Every write path in this codebase runs inside `write_transaction()`, which
serialises concurrent writers. For SQLite this uses `BEGIN IMMEDIATE`;
for PostgreSQL it uses a regular BEGIN (server-side serialisation via MVCC).

The module-level helpers (write_transaction, query, query_one) delegate
to the backend registered on the Flask app via app.extensions["db"].
"""
from __future__ import annotations

import abc
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

BUSY_TIMEOUT_MS = 10_000


# ── Abstract base ─────────────────────────────────────────────────────────────

class DatabaseBackend(abc.ABC):
    """Minimal interface that all database backends must implement.

    Concrete subclasses: SQLiteBackend, PostgreSQLBackend.
    """

    @contextmanager
    @abc.abstractmethod
    def write_transaction(self) -> Iterator[Any]:
        """Serialised read-write transaction. Yields a DB-API 2.0 connection.
        Commits on success; rolls back on exception.
        """
        yield  # pragma: no cover

    @contextmanager
    @abc.abstractmethod
    def read_transaction(self) -> Iterator[Any]:
        """Read-only transaction. Yields a DB-API 2.0 connection."""
        yield  # pragma: no cover

    @abc.abstractmethod
    def query(self, sql: str, params: Sequence[Any] = ()) -> list[Any]:
        """Execute *sql* and return all rows as a list."""

    @abc.abstractmethod
    def query_one(self, sql: str, params: Sequence[Any] = ()) -> Any | None:
        """Execute *sql* and return the first row, or None."""

    @abc.abstractmethod
    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        """Execute *sql* without returning rows (INSERT/UPDATE/DELETE)."""

    @abc.abstractmethod
    def executescript(self, sql: str) -> None:
        """Execute a multi-statement SQL script (used by migrations)."""

    @abc.abstractmethod
    def close(self) -> None:
        """Release all connections held by the current thread."""


# ── SQLite backend ─────────────────────────────────────────────────────────────

class SQLiteBackend(DatabaseBackend):
    """SQLite backend using the stdlib sqlite3 module.

    • One connection per thread (thread-local storage).
    • ``BEGIN IMMEDIATE`` serialises all writers.
    • WAL mode for concurrent readers.
    """

    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

    # -- connection -------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path,
            isolation_level=None,   # explicit transactions only
            timeout=BUSY_TIMEOUT_MS / 1000,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @property
    def connection(self) -> sqlite3.Connection:
        """One connection per thread; SQLite connections are not thread-safe."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self.connect()
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # -- transactions -----------------------------------------------------
    @contextmanager
    def write_transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialised read-write transaction. Commits on success, rolls back on error."""
        conn = self.connection
        if conn.in_transaction:
            # Nested use joins the outer boundary; the outermost owns commit.
            yield conn
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

    @contextmanager
    def read_transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connection
        if conn.in_transaction:
            yield conn
            return
        conn.execute("BEGIN")
        try:
            yield conn
        finally:
            conn.execute("COMMIT")

    # -- helpers ----------------------------------------------------------
    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return list(self.connection.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return self.connection.execute(sql, params).fetchone()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, params)

    def executescript(self, sql: str) -> None:
        self.connection.executescript(sql)


# ── Database alias (backward compat) ──────────────────────────────────────────

#: Backward-compatible alias so all existing ``Database(path)`` calls keep
#: working without modification.
Database = SQLiteBackend


# ── PostgreSQL backend ─────────────────────────────────────────────────────────

class _PgRow(dict):
    """Dict-like row compatible with sqlite3.Row for column-name access."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _adapt_sql(sql: str, params: Sequence[Any] | None = None) -> str:
    """Convert SQLite ``?`` placeholders to psycopg2 ``%s`` placeholders.

    Uses a context-aware scanner that correctly skips ``?`` characters that
    appear inside:
      - Single-quoted string literals  ('don''t', 'URL?param=1')
      - Double-quoted identifiers      ("column?name")
      - Line comments                  (-- anything ? here)
      - Block comments                 (/* nested /* ok */ ? still in comment */)
      - Dollar-quoted strings          ($$body with ? inside$$, $tag$body$tag$)

    Only a bare ``?`` that is a true positional parameter placeholder is
    converted to ``%s``.

    Literal ``%`` characters outside placeholders are doubled (``%%``) so
    that psycopg2 does not interpret them as format specifiers.

    Args:
        sql:    The SQL string, possibly containing SQLite-style ``?``
                placeholders.
        params: The parameter sequence that will be bound.  When provided,
                the converted placeholder count is validated against
                ``len(params)`` and a ``ValueError`` is raised on mismatch.

    Returns:
        The adapted SQL string with ``?`` replaced by ``%s`` (where they are
        true placeholders) and bare ``%`` doubled to ``%%``.

    Raises:
        ValueError: If *params* is provided and the placeholder count does not
                    match ``len(params)``.
    """
    # ── Sentinel for real placeholder positions ───────────────────────────────
    # We mark each real `?` placeholder with STX (\x02) during scanning so
    # that after the scan we can:
    #   1. replace ALL `%` with `%%` (psycopg2 requires this everywhere,
    #      including inside quoted literals where `%` appears, e.g. LIKE '%foo%')
    #   2. replace our \x02 sentinels with `%s`
    # \x02 (ASCII STX) never appears in valid SQL source.
    _SENTINEL = "\x02"

    result: list[str] = []
    i = 0
    n = len(sql)
    placeholder_count = 0

    # State flags
    in_single_quote: bool = False
    in_double_quote: bool = False
    block_depth: int = 0          # nesting depth for /* ... */ comments
    in_line_comment: bool = False
    in_dollar_quote: str | None = None  # the tag e.g. "$$" or "$body$"

    while i < n:
        ch = sql[i]

        # ── Line comment: ends at newline ────────────────────────────────────
        if in_line_comment:
            result.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        # ── Block comment: nested, ends at matching */ ────────────────────────
        if block_depth > 0:
            if sql[i:i+2] == "/*":
                block_depth += 1
                result.append("/*")
                i += 2
            elif sql[i:i+2] == "*/":
                block_depth -= 1
                result.append("*/")
                i += 2
            else:
                result.append(ch)
                i += 1
            continue

        # ── Dollar-quoted string ──────────────────────────────────────────────
        if in_dollar_quote is not None:
            tag = in_dollar_quote
            if sql[i:i+len(tag)] == tag:
                result.append(tag)
                i += len(tag)
                in_dollar_quote = None
            else:
                result.append(ch)
                i += 1
            continue

        # ── Single-quoted literal ─────────────────────────────────────────────
        if in_single_quote:
            if ch == "'" and i + 1 < n and sql[i+1] == "'":
                # Escaped quote ''
                result.append("''")
                i += 2
            elif ch == "'":
                in_single_quote = False
                result.append(ch)
                i += 1
            else:
                result.append(ch)
                i += 1
            continue

        # ── Double-quoted identifier ──────────────────────────────────────────
        if in_double_quote:
            if ch == '"' and i + 1 < n and sql[i+1] == '"':
                result.append('""')
                i += 2
            elif ch == '"':
                in_double_quote = False
                result.append(ch)
                i += 1
            else:
                result.append(ch)
                i += 1
            continue

        # ── Detect start of contexts ──────────────────────────────────────────

        # Line comment --
        if sql[i:i+2] == "--":
            in_line_comment = True
            result.append("--")
            i += 2
            continue

        # Block comment /*
        if sql[i:i+2] == "/*":
            block_depth += 1
            result.append("/*")
            i += 2
            continue

        # Dollar quoting: $tag$ or $$
        if ch == "$":
            import re as _re2
            dq_match = _re2.match(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$", sql[i:])
            if dq_match:
                tag = dq_match.group(0)
                in_dollar_quote = tag
                result.append(tag)
                i += len(tag)
                continue

        # Single-quote
        if ch == "'":
            in_single_quote = True
            result.append(ch)
            i += 1
            continue

        # Double-quote
        if ch == '"':
            in_double_quote = True
            result.append(ch)
            i += 1
            continue

        # ── Placeholder: mark with sentinel ──────────────────────────────────
        if ch == "?":
            placeholder_count += 1
            result.append(_SENTINEL)
            i += 1
            continue

        result.append(ch)
        i += 1

    # ── Post-scan: double ALL % → %%, then substitute sentinels → %s ─────────
    # psycopg2 treats the entire SQL string (including quoted literals) as a
    # Python %-format string, so every literal `%` must be doubled to `%%`.
    # We then restore our sentinel positions as `%s` (the psycopg2 placeholder).
    adapted = "".join(result).replace("%", "%%").replace(_SENTINEL, "%s")

    if params is not None:
        expected = len(params)
        if placeholder_count != expected:
            raise ValueError(
                f"_adapt_sql: placeholder count mismatch — "
                f"SQL has {placeholder_count} '?' but {expected} parameters were provided. "
                f"SQL (first 200 chars): {sql[:200]!r}"
            )

    return adapted


# ── PostgreSQL connection shim ─────────────────────────────────────────────────

class _PgCursorShim:
    """Wraps a psycopg2 cursor to expose a sqlite3.Cursor-compatible interface.

    Key differences bridged:
    * ``lastrowid`` — psycopg2 does not set this; populated via ``lastval()``
      after every INSERT statement.
    * ``fetchone()`` / ``fetchall()`` — return ``_PgRow`` dicts so callers can
      use both column-name and integer-index access.
    * ``rowcount`` — delegated directly to the psycopg2 cursor.
    """

    def __init__(self, cur, lastrowid: int | None = None):
        self._cur = cur
        self._lastrowid = lastrowid

    # ---- sqlite3.Cursor compatibility ----------------------------------------
    @property
    def lastrowid(self) -> int | None:
        return self._lastrowid

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def fetchone(self) -> _PgRow | None:
        row = self._cur.fetchone()
        if row is None:
            return None
        if self._cur.description is None:
            return None
        cols = [d[0] for d in self._cur.description]
        return _PgRow(zip(cols, row))

    def fetchall(self) -> list[_PgRow]:
        if self._cur.description is None:
            return []
        cols = [d[0] for d in self._cur.description]
        return [_PgRow(zip(cols, row)) for row in self._cur.fetchall()]

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row


class _PgConnectionShim:
    """Wraps a psycopg2 connection to expose a sqlite3.Connection-compatible interface.

    All existing application code uses ``conn.execute(sql, params)`` patterns
    from sqlite3.  psycopg2 connections only expose ``cursor()`` — they have
    no ``execute()`` method.  This shim bridges that gap so every caller works
    unchanged regardless of which backend is active.

    SQL adaptation performed on every call:
    * ``?`` → ``%s`` placeholder conversion (via ``_adapt_sql``).
    * ``datetime('now')`` → PostgreSQL equivalent (ISO-8601 UTC text).
    * ``strftime(…, 'now')`` → PostgreSQL equivalent.
    * ``instr(col, 'x')`` → ``position('x' IN col)``.

    ``lastrowid`` is populated after INSERT statements using ``lastval()``.
    """

    def __init__(self, pg_conn):
        self._conn = pg_conn
        self._last_rowcount: int = 0

    def execute(self, sql: str, params: Sequence[Any] = ()) -> _PgCursorShim:
        # Pass params for placeholder-count validation inside _adapt_pg_sql.
        adapted = _adapt_pg_sql(sql, params if params else None)
        cur = self._conn.cursor()
        cur.execute(adapted, params if params else None)

        # Track rowcount for total_changes compatibility (UPDATE/DELETE affected rows).
        self._last_rowcount = cur.rowcount if cur.rowcount >= 0 else 0

        # Populate lastrowid for INSERT statements via lastval()
        lastrowid: int | None = None
        if adapted.strip().upper().startswith("INSERT"):
            try:
                id_cur = self._conn.cursor()
                id_cur.execute("SELECT lastval()")
                row = id_cur.fetchone()
                lastrowid = int(row[0]) if row else None
                id_cur.close()
            except Exception:
                lastrowid = None

        return _PgCursorShim(cur, lastrowid=lastrowid)

    def executemany(self, sql: str, params_seq) -> None:
        adapted = _adapt_pg_sql(sql)
        with self._conn.cursor() as cur:
            for params in params_seq:
                cur.execute(adapted, params)

    # Expose in_transaction-like attribute (always True inside write_transaction)
    @property
    def in_transaction(self) -> bool:
        return True

    # SQLite compatibility: number of rows changed by the last DML statement.
    # Application code checks ``conn.total_changes == 0`` to detect a no-op UPDATE.
    @property
    def total_changes(self) -> int:
        return self._last_rowcount


def _adapt_pg_sql(sql: str, params: Sequence[Any] | None = None) -> str:
    """Translate SQLite-specific SQL to PostgreSQL syntax.

    Handles:
    * ``?`` → ``%s`` parameter placeholders (context-aware, safe scanner).
    * ``datetime('now')`` → ISO-8601 UTC timestamp text.
    * ``strftime('%Y-%m-%dT%H:%M:%SZ', 'now')`` and similar → UTC text.
    * ``instr(col, 'x') > 0`` → ``position('x' IN col) > 0``.
    * ``datetime(col)`` used for comparison normalisation → ``col::timestamp``.

    When *params* is provided the placeholder count is validated against
    ``len(params)`` by ``_adapt_sql``.
    """
    import re as _re

    # ? → %s via context-aware scanner (skips quoted strings, comments, etc.)
    sql = _adapt_sql(sql, params)

    # datetime('now') → to_char(timezone('UTC', NOW()), 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"')
    _dt_now = "to_char(timezone('UTC', NOW()), 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"')"
    sql = _re.sub(r"datetime\(\s*'now'\s*\)", _dt_now, sql, flags=_re.IGNORECASE)

    # strftime('%Y-%m-%dT%H:%M:%fZ', 'now') and variants → same UTC text
    sql = _re.sub(
        r"strftime\(\s*'[^']+'\s*,\s*'now'\s*\)",
        _dt_now,
        sql, flags=_re.IGNORECASE,
    )

    # instr(col, 'char') > 0  →  position('char' IN col) > 0
    sql = _re.sub(
        r"\binstr\(\s*(\w+)\s*,\s*'([^']*)'\s*\)\s*>\s*0",
        r"position('\2' IN \1) > 0",
        sql, flags=_re.IGNORECASE,
    )

    # datetime(expr) used as comparison normaliser in WHERE clauses
    # e.g.  datetime(next_attempt_at) <= datetime(?)
    # In PostgreSQL, cast to timestamp achieves the same normalisation.
    sql = _re.sub(
        r"\bdatetime\(\s*(\?|%s|[a-zA-Z_][a-zA-Z0-9_.]*)\s*\)",
        r"(\1)::timestamp",
        sql, flags=_re.IGNORECASE,
    )

    # INSERT OR IGNORE INTO … → INSERT INTO … ON CONFLICT DO NOTHING
    # SQLite-style conflict-ignore shorthand used in application DML (not just migrations).
    sql = _re.sub(
        r'(INSERT)\s+OR\s+IGNORE\s+(INTO\b[^;]*)',
        r'\1 \2 ON CONFLICT DO NOTHING',
        sql, flags=_re.IGNORECASE | _re.DOTALL,
    )

    # MAX(literal, expr) → GREATEST(literal, expr)
    # SQLite treats max() as a scalar function when called with two arguments.
    # PostgreSQL's max() is aggregate-only; GREATEST() is the scalar two-arg form.
    sql = _re.sub(
        r'\bMAX\s*\(\s*(\d+)\s*,',
        r'GREATEST(\1,',
        sql, flags=_re.IGNORECASE,
    )

    return sql


def _pg_adapt_migration(sql: str) -> str:
    """Translate SQLite DDL/DML to PostgreSQL syntax for migration scripts.

    Applied once per migration before statement splitting and execution.

    Handles:
    * ``INTEGER PRIMARY KEY AUTOINCREMENT`` → ``SERIAL PRIMARY KEY``
    * ``DEFAULT (datetime('now'))`` → ``DEFAULT NOW()::TEXT``
    * ``DEFAULT (strftime(…, 'now'))`` → ``DEFAULT NOW()::TEXT``
    * ``instr(col, 'x') > 0`` → ``position('x' IN col) > 0``
    * ``DROP TABLE [IF EXISTS] x`` → ``DROP TABLE [IF EXISTS] x CASCADE``
      so FK references are released and the table can be dropped without error.
    * ``INSERT OR IGNORE INTO`` → ``INSERT INTO … ON CONFLICT DO NOTHING``
      preserving idempotent seed-insert behaviour.
    * ``PRAGMA …`` statements → removed entirely (no-op on PostgreSQL).
    """
    import re as _re

    # INTEGER PRIMARY KEY AUTOINCREMENT → SERIAL PRIMARY KEY
    # SERIAL maps to INT4, matching the INTEGER type of FK columns.
    sql = _re.sub(
        r'\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b',
        'SERIAL PRIMARY KEY',
        sql, flags=_re.IGNORECASE,
    )

    # DEFAULT (datetime('now')) → DEFAULT NOW()::TEXT
    # NOW()::TEXT stores the timestamp as a text string, preserving TEXT column type.
    sql = _re.sub(
        r"DEFAULT\s+\(\s*datetime\s*\(\s*'now'\s*\)\s*\)",
        "DEFAULT NOW()::TEXT",
        sql, flags=_re.IGNORECASE,
    )

    # DEFAULT (strftime('%Y-…', 'now')) → DEFAULT NOW()::TEXT
    # Handles both with-space and no-space variants.
    sql = _re.sub(
        r"DEFAULT\s+\(\s*strftime\s*\(\s*'[^']*'\s*,\s*'now'\s*\)\s*\)",
        "DEFAULT NOW()::TEXT",
        sql, flags=_re.IGNORECASE,
    )

    # instr(col, 'x') > 0 → position('x' IN col) > 0
    sql = _re.sub(
        r"\binstr\(\s*(\w+)\s*,\s*'([^']*)'\s*\)\s*>\s*0",
        r"position('\2' IN \1) > 0",
        sql, flags=_re.IGNORECASE,
    )

    # DROP TABLE [IF EXISTS] tablename → DROP TABLE [IF EXISTS] tablename CASCADE
    # PostgreSQL cannot DROP a table while FK constraints from other tables reference
    # it unless CASCADE is specified.  CASCADE drops those FK constraint definitions
    # (not the referencing tables themselves).
    sql = _re.sub(
        r'(DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?\w+)(?!\s+CASCADE)',
        r'\1 CASCADE',
        sql, flags=_re.IGNORECASE,
    )

    # INSERT OR IGNORE INTO … ; → INSERT INTO … ON CONFLICT DO NOTHING ;
    # Translates SQLite's conflict-ignore shorthand to the SQL-standard clause.
    sql = _re.sub(
        r'(INSERT)\s+OR\s+IGNORE\s+(INTO\b[^;]+)',
        r'\1 \2 ON CONFLICT DO NOTHING',
        sql, flags=_re.IGNORECASE | _re.DOTALL,
    )

    # PRAGMA … ; → remove entirely (SQLite-only, silently ignored on PostgreSQL
    # by removal rather than passing through so psycopg2 never sees them).
    sql = _re.sub(
        r'^\s*PRAGMA\s+[^;\n]*;?\s*$',
        '',
        sql, flags=_re.IGNORECASE | _re.MULTILINE,
    )

    return sql


class PostgreSQLBackend(DatabaseBackend):
    """PostgreSQL backend via psycopg2.

    Requires the ``psycopg2`` (or ``psycopg2-binary``) package.  A lazy
    import is used so that the class can be imported in environments where
    psycopg2 is not installed; it will raise a clear RuntimeError only when
    the class is *instantiated*.

    Transaction model: unlike SQLiteBackend (BEGIN IMMEDIATE), PostgreSQL
    uses standard BEGIN / COMMIT with MVCC for concurrent isolation.
    Row-level locking (``SELECT … FOR UPDATE SKIP LOCKED``) should be used
    in queue-style claiming; the outbox worker uses ``FOR UPDATE SKIP LOCKED``
    automatically when running against PostgreSQL.

    Connection reuse: one persistent connection per thread, matching the
    SQLiteBackend pattern.  Replace with a connection pool for production.

    The ``write_transaction()`` context manager yields a ``_PgConnectionShim``
    that exposes ``conn.execute(sql, params)`` so all existing callers work
    unchanged regardless of which backend is active.
    """

    def __init__(self, dsn: str):
        """*dsn* is a libpq connection string or ``postgresql://…`` URL."""
        try:
            import psycopg2  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "psycopg2 is required for PostgreSQLBackend. "
                "Install it with: pip install psycopg2-binary"
            ) from exc
        self._dsn = dsn
        self._local = threading.local()

    def _connect(self):
        import psycopg2
        conn = psycopg2.connect(self._dsn)
        conn.autocommit = False
        return conn

    @property
    def connection(self):
        conn = getattr(self._local, "conn", None)
        if conn is None or conn.closed:
            conn = self._connect()
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None and not conn.closed:
            conn.close()
        self._local.conn = None

    def _rows(self, cursor) -> list[_PgRow]:
        if cursor.description is None:
            return []
        cols = [d[0] for d in cursor.description]
        return [_PgRow(zip(cols, row)) for row in cursor.fetchall()]

    def _one(self, cursor) -> _PgRow | None:
        if cursor.description is None:
            return None
        row = cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cursor.description]
        return _PgRow(zip(cols, row))

    @contextmanager
    def write_transaction(self) -> Iterator[Any]:
        """Yield a ``_PgConnectionShim`` with ``conn.execute()`` compatible with sqlite3."""
        conn = self.connection
        shim = _PgConnectionShim(conn)
        try:
            yield shim
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise

    @contextmanager
    def read_transaction(self) -> Iterator[Any]:
        """Yield a ``_PgConnectionShim`` for read operations."""
        conn = self.connection
        shim = _PgConnectionShim(conn)
        try:
            yield shim
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[_PgRow]:
        conn = self.connection
        with conn.cursor() as cur:
            cur.execute(_adapt_pg_sql(sql), params or None)
            return self._rows(cur)

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> _PgRow | None:
        conn = self.connection
        with conn.cursor() as cur:
            cur.execute(_adapt_pg_sql(sql), params or None)
            return self._one(cur)

    def execute(self, sql: str, params: Sequence[Any] = ()):
        conn = self.connection
        with conn.cursor() as cur:
            cur.execute(_adapt_pg_sql(sql), params or None)
            return cur

    def executescript(self, sql: str) -> None:
        """Execute a multi-statement migration script on PostgreSQL.

        Performs SQL translation (AUTOINCREMENT, datetime defaults, instr,
        DROP TABLE CASCADE, INSERT OR IGNORE → ON CONFLICT DO NOTHING, PRAGMA
        removal) before splitting on semicolons and executing each statement.

        Transaction management:
        * Skips embedded ``BEGIN``/``COMMIT``/``ROLLBACK`` (they are SQLite
          migration-pattern artefacts; psycopg2 manages the transaction).
        * Commits at the end on success; rolls back on any exception.
          This ensures DDL is durable after ``executescript()`` returns, which
          is the same guarantee SQLite's ``executescript()`` provides.
        """
        adapted = _pg_adapt_migration(sql)
        conn = self.connection
        try:
            with conn.cursor() as cur:
                for stmt in adapted.split(";"):
                    stmt = stmt.strip()
                    if not stmt:
                        continue
                    upper = stmt.upper()
                    # Skip explicit transaction control — psycopg2 manages this
                    if upper in ("BEGIN", "COMMIT", "ROLLBACK"):
                        continue
                    cur.execute(stmt)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise


# ── Factory: pick backend from DATABASE_URL ────────────────────────────────────

def make_backend(database_url: str) -> DatabaseBackend:
    """Instantiate the correct DatabaseBackend from *database_url*.

    ``sqlite:///path/to/db``  → SQLiteBackend
    ``postgresql://…``        → PostgreSQLBackend  (requires psycopg2)
    ``postgres://…``          → PostgreSQLBackend  (alias)
    """
    if database_url.startswith("sqlite:///"):
        path = database_url[len("sqlite:///"):]
        return SQLiteBackend(path)
    if database_url.startswith(("postgresql://", "postgres://")):
        return PostgreSQLBackend(database_url)
    raise ValueError(
        f"Unsupported DATABASE_URL scheme: {database_url!r}. "
        "Supported: sqlite:/// or postgresql://"
    )


# ── Module-level helpers (use Flask's current_app db) ──────────────────────

from contextlib import contextmanager as _contextmanager  # noqa: E402


def _get_db() -> "DatabaseBackend":
    """Return the DatabaseBackend bound to the current Flask app."""
    from flask import current_app
    return current_app.extensions["db"]


@_contextmanager
def write_transaction():
    """Context manager: serialised read-write transaction on the app db."""
    with _get_db().write_transaction() as conn:
        yield conn


def query(sql: str, params=(), *, one: bool = False):
    """Run a SELECT; return a single row (or None) when one=True, else all rows."""
    db = _get_db()
    if one:
        return db.query_one(sql, params)
    return db.query(sql, params)


def query_one(sql: str, params=()):
    """Run a SELECT and return one row or None."""
    return _get_db().query_one(sql, params)
