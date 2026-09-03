"""
Converts SQLite migration files → PostgreSQL-native migration files.

Key transformations:
  - INTEGER PRIMARY KEY AUTOINCREMENT → BIGSERIAL PRIMARY KEY
  - INTEGER NOT NULL/NULL column defs → INTEGER (kept, PG supports it)
  - DEFAULT (datetime('now')) → DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
  - instr(col, 'x') → POSITION('x' IN col)
  - CREATE TRIGGER ... BEGIN SELECT RAISE(ABORT,...) END → PG trigger function + trigger
  - INSERT OR IGNORE → INSERT ... ON CONFLICT DO NOTHING
  - PRAGMA ... → (removed)
  - BEGIN / COMMIT / ROLLBACK standalone lines → (removed)

The migrator will use backend/migrations_postgresql/ for PostgreSQL backend.
"""
import re
import os

SRC = "migrations"
DST = "migrations_postgresql"
os.makedirs(DST, exist_ok=True)

TS_DEFAULT = "TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"+00:00\"')"


def convert(sql: str, filename: str) -> str:
    lines = sql.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip PRAGMA statements
        if stripped.upper().startswith("PRAGMA"):
            i += 1
            continue

        # Skip standalone transaction keywords in migrations
        if stripped.upper() in ("BEGIN;", "BEGIN IMMEDIATE;", "COMMIT;", "ROLLBACK;",
                                 "BEGIN", "BEGIN IMMEDIATE", "COMMIT", "ROLLBACK"):
            i += 1
            continue

        # Collect multi-line CREATE TRIGGER blocks
        if stripped.upper().startswith("CREATE TRIGGER"):
            trigger_lines = [line]
            i += 1
            while i < len(lines):
                trigger_lines.append(lines[i])
                if lines[i].strip().upper() == "END;" or lines[i].strip().upper() == "END":
                    i += 1
                    break
                i += 1
            pg_trigger = convert_trigger("\n".join(trigger_lines))
            out.append(pg_trigger)
            continue

        # Transform INSERT OR IGNORE
        if re.match(r"\s*INSERT\s+OR\s+IGNORE\s+", stripped, re.IGNORECASE):
            line = re.sub(r"INSERT\s+OR\s+IGNORE\s+", "INSERT ", line, flags=re.IGNORECASE)
            # We'll add ON CONFLICT DO NOTHING at end, but need to handle multi-line
            # Collect until the semicolon
            stmt_lines = [line]
            i += 1
            while i < len(lines) and ";" not in lines[i]:
                stmt_lines.append(lines[i])
                i += 1
            if i < len(lines):
                stmt_lines.append(lines[i])
                i += 1
            stmt = "\n".join(stmt_lines)
            # Add ON CONFLICT DO NOTHING before the final semicolon
            stmt = re.sub(r";\s*$", " ON CONFLICT DO NOTHING;", stmt.rstrip())
            out.append(stmt)
            continue

        # Transform the line
        line = transform_line(line)
        out.append(line)
        i += 1

    return "\n".join(out)


def transform_line(line: str) -> str:
    # INTEGER PRIMARY KEY AUTOINCREMENT → BIGSERIAL PRIMARY KEY
    line = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "BIGSERIAL PRIMARY KEY",
        line, flags=re.IGNORECASE
    )

    # DEFAULT (datetime('now')) → DEFAULT TS_DEFAULT
    line = re.sub(
        r"DEFAULT\s+\(datetime\('now'\)\)",
        f"DEFAULT {TS_DEFAULT}",
        line, flags=re.IGNORECASE
    )

    # instr(col, 'char') → POSITION('char' IN col)
    def replace_instr(m):
        col = m.group(1).strip()
        char = m.group(2).strip()
        return f"POSITION({char} IN {col})"

    line = re.sub(
        r"\binstr\s*\(\s*([^,]+),\s*('[^']*')\s*\)",
        replace_instr,
        line, flags=re.IGNORECASE
    )

    # datetime(col) used in WHERE comparisons → col::timestamp
    # e.g. datetime(next_attempt_at) <= datetime(?) — handled in app code not migrations

    return line


def convert_trigger(block: str) -> str:
    """Convert a SQLite CREATE TRIGGER block to PostgreSQL trigger syntax."""
    # Extract trigger name
    name_match = re.search(r"CREATE\s+TRIGGER\s+(\w+)", block, re.IGNORECASE)
    trigger_name = name_match.group(1) if name_match else "unknown_trigger"

    # Extract timing (BEFORE/AFTER)
    timing_match = re.search(r"\b(BEFORE|AFTER)\b", block, re.IGNORECASE)
    timing = timing_match.group(1).upper() if timing_match else "BEFORE"

    # Extract event (UPDATE/DELETE/INSERT)
    event_match = re.search(r"\b(UPDATE|DELETE|INSERT)\b\s+ON", block, re.IGNORECASE)
    event = event_match.group(1).upper() if event_match else "UPDATE"

    # Extract table name
    table_match = re.search(r"\bON\s+(\w+)\b", block, re.IGNORECASE)
    table_name = table_match.group(1) if table_match else "unknown_table"

    # Extract the RAISE message
    raise_match = re.search(r"RAISE\s*\(\s*ABORT\s*,\s*'([^']+)'\s*\)", block, re.IGNORECASE)
    raise_msg = raise_match.group(1) if raise_match else f"{trigger_name}: forbidden"

    fn_name = f"{trigger_name}_fn"

    pg = f"""CREATE OR REPLACE FUNCTION {fn_name}() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '{raise_msg}' USING ERRCODE = '23000';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER {trigger_name}
{timing} {event} ON {table_name}
FOR EACH ROW EXECUTE PROCEDURE {fn_name}();"""
    return pg


# Process each migration file
import glob

for src_path in sorted(glob.glob(f"{SRC}/*.sql")):
    fname = os.path.basename(src_path)
    with open(src_path, encoding="utf-8") as f:
        sql = f.read()
    pg_sql = convert(sql, fname)
    dst_path = os.path.join(DST, fname)
    with open(dst_path, "w", encoding="utf-8") as f:
        f.write(pg_sql)
    print(f"Converted: {fname}")

print("Done.")
