"""Convert one SQLite migration (backend/migrations) into its PostgreSQL twin (backend/migrations_postgresql).

Usage:  python3 scripts/sqlite_to_pg_migration.py 0041_commerce_ops.sql [more.sql ...]

Statement-by-statement, so nothing after a trigger is ever dropped (the old generator's failure).
  * INTEGER PRIMARY KEY [AUTOINCREMENT]      → BIGSERIAL PRIMARY KEY
  * <name>_minor INTEGER                     → BIGINT (Rial amounts overflow 32-bit integers)
  * datetime('now') / strftime(...,'now')    → UTC ISO-8601 text, same shape SQLite writes
  * INSERT OR IGNORE                         → INSERT ... ON CONFLICT DO NOTHING
  * CREATE TRIGGER ... [WHEN c] BEGIN b END  → plpgsql function + trigger; WHEN moves into the body
    (PostgreSQL forbids sub-queries in a trigger's WHEN), RAISE(ABORT,'m') → RAISE EXCEPTION 'm',
    and SQLite's NULL-safe `a IS NOT b` / `a IS b` become IS [NOT] DISTINCT FROM.
Review the output: it is a starting point checked by running it on a real PostgreSQL, not a guarantee.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC, DST = ROOT / "migrations", ROOT / "migrations_postgresql"

TS = "to_char(timezone('UTC', now()), 'YYYY-MM-DD\"T\"HH24:MI:SS\"+00:00\"')"
TS_MS = "to_char(timezone('UTC', now()), 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"')"


def split_statements(sql: str) -> list[str]:
    """Split on ';' outside quotes/comments, keeping CREATE TRIGGER ... BEGIN ... END; whole."""
    out, cur, i, n = [], [], 0, len(sql)
    quote = None
    depth = 0  # BEGIN ... END nesting inside a trigger
    while i < n:
        ch = sql[i]
        if quote:
            cur.append(ch)
            if ch == quote:
                if i + 1 < n and sql[i + 1] == quote:
                    cur.append(sql[i + 1])
                    i += 1
                else:
                    quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            cur.append(ch)
            i += 1
            continue
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j == -1 else j
            cur.append(sql[i:j])
            i = j
            continue
        word = re.match(r"[A-Za-z_]+", sql[i:])
        if word and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")):
            w = word.group(0).upper()
            text = "".join(cur)
            if w == "BEGIN" and re.search(r"\bCREATE\s+TRIGGER\b", text, re.I):
                depth += 1
            elif w == "CASE" and depth:
                depth += 1
            elif w == "END" and depth:
                depth -= 1
            cur.append(word.group(0))
            i += len(word.group(0))
            continue
        if ch == ";" and depth == 0:
            stmt = "".join(cur).strip()
            if _has_code(stmt):
                out.append(stmt)
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    tail = "".join(cur).strip()
    if _has_code(tail):
        out.append(tail)
    return out


def _has_code(stmt: str) -> bool:
    return any(line.strip() and not line.strip().startswith("--") for line in stmt.splitlines())


def _strip_comments(stmt: str) -> str:
    return "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()


def common(sql: str) -> str:
    sql = re.sub(r"strftime\(\s*'%Y-%m-%dT%H:%M:%fZ'\s*,\s*'now'\s*\)", TS_MS, sql)
    sql = re.sub(r"strftime\(\s*'%Y-%m-%dT%H:%M:%SZ'\s*,\s*'now'\s*\)", TS, sql)
    sql = re.sub(r"datetime\(\s*'now'\s*\)", TS, sql, flags=re.I)
    sql = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY(\s+AUTOINCREMENT)?", "BIGSERIAL PRIMARY KEY", sql, flags=re.I)
    sql = re.sub(r"\b(\w+_minor)\s+INTEGER\b", r"\1 BIGINT", sql)
    return sql


def null_safe(cond: str) -> str:
    cond = re.sub(r"\bIS\s+NOT\s+(?!NULL\b|DISTINCT\b)", "IS DISTINCT FROM ", cond, flags=re.I)
    cond = re.sub(r"\bIS\s+(?!NOT\b|NULL\b|DISTINCT\b)", "IS NOT DISTINCT FROM ", cond, flags=re.I)
    return cond


TRIGGER_RE = re.compile(
    r"CREATE\s+TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+(BEFORE|AFTER)\s+"
    r"(INSERT|DELETE|UPDATE(?:\s+OF\s+[\w\s,]+?)?)\s+ON\s+(\w+)\s*"
    r"(?:FOR\s+EACH\s+ROW\s*)?(?:WHEN\s+(.*?)\s*)?\bBEGIN\b(.*)\bEND\s*$",
    re.I | re.S,
)


def convert_trigger(stmt: str) -> str:
    m = TRIGGER_RE.match(_strip_comments(stmt))
    if not m:
        raise ValueError(f"unsupported trigger:\n{stmt}")
    name, timing, event, table, when, body = m.groups()
    event = re.sub(r"\s+", " ", event.strip())
    lines = []
    for part in split_statements(body):
        part = part.strip()
        raise_m = re.fullmatch(r"SELECT\s+RAISE\s*\(\s*ABORT\s*,\s*('(?:[^']|'')*')\s*\)", part, re.I | re.S)
        if raise_m:
            lines.append(f"RAISE EXCEPTION {raise_m.group(1)} USING ERRCODE = '23000';")
        elif re.search(r"\bRAISE\s*\(", part, re.I):
            raise ValueError(f"unsupported RAISE form in trigger {name}: {part}")
        else:
            lines.append(common(part) + ";")
    ret = "OLD" if event.upper() == "DELETE" else "NEW"
    inner = "\n    ".join(lines)
    if when:
        inner = f"IF {null_safe(when.strip())} THEN\n        {inner.replace(chr(10), chr(10) + '    ')}\n    END IF;"
    fn = f"{name}_fn"
    return (
        f"CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger AS $$\nBEGIN\n    {inner}\n    RETURN {ret};\nEND;\n$$ LANGUAGE plpgsql;\n\n"
        f"CREATE TRIGGER {name}\n{timing.upper()} {event.upper().replace(' OF ', ' OF ')} ON {table}\n"
        f"FOR EACH ROW EXECUTE PROCEDURE {fn}();"
    )


def convert(sql: str) -> str:
    out = []
    for stmt in split_statements(sql):
        code = _strip_comments(stmt)
        upper = code.upper()
        if upper.startswith("PRAGMA") or upper in ("BEGIN", "BEGIN IMMEDIATE", "BEGIN TRANSACTION", "COMMIT", "ROLLBACK"):
            continue
        comments = "\n".join(l for l in stmt.splitlines() if l.strip().startswith("--"))
        if re.match(r"CREATE\s+TRIGGER\b", code, re.I):
            body = convert_trigger(stmt)
        else:
            body = common(code)
            if re.match(r"INSERT\s+OR\s+IGNORE\b", body, re.I):
                body = re.sub(r"INSERT\s+OR\s+IGNORE", "INSERT", body, count=1, flags=re.I) + "\nON CONFLICT DO NOTHING"
            elif re.match(r"INSERT\s+OR\s+REPLACE\b", body, re.I):
                raise ValueError("INSERT OR REPLACE needs a hand-written ON CONFLICT clause:\n" + code)
            body += ";"
        out.append((comments + "\n" if comments else "") + body)
    return "\n\n".join(out) + "\n"


def main(names: list[str]) -> None:
    for name in names:
        src = (SRC / name).read_text(encoding="utf-8")
        header = f"-- PostgreSQL twin of migrations/{name}, generated by scripts/sqlite_to_pg_migration.py\n\n"
        (DST / name).write_text(header + convert(src), encoding="utf-8")
        print("wrote", DST / name)


if __name__ == "__main__":
    main(sys.argv[1:])
