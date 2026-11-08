"""0043: preserve the SQLite original table as a rollback archive; no DROP.

SQLite has no ALTER COLUMN DROP NOT NULL. legacy_alter_table plus FK OFF
keeps inbound references pointing to the canonical name during reconstruction.
Only unit/package constraints/defaults change. No runtime reads use the archive.
"""
import re

ARCHIVE = '_rollback_0043_master_products'


def apply(conn, *, checksum, now):
    if conn.in_transaction:
        raise ValueError('Nullable migration requires its own transaction')
    if conn.execute("SELECT 1 FROM schema_migrations WHERE version='0043'").fetchone():
        return False
    original = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='master_products'").fetchone()[0]
    updated, units = re.subn(r"(\bunit\s+TEXT)\s+NOT NULL\s+DEFAULT 'عدد'", r'\1', original)
    updated, packs = re.subn(r'(\bpackage_quantity\s+INTEGER)\s+NOT NULL\s+DEFAULT 1', r'\1', updated)
    if (units, packs) != (1, 1):
        raise ValueError('Unexpected master schema; review before migration')
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (ARCHIVE,)).fetchone():
        raise ValueError('Rollback archive already exists')
    indices = conn.execute("SELECT name,sql FROM sqlite_master WHERE tbl_name='master_products' AND type='index' AND sql IS NOT NULL").fetchall()
    if conn.execute("SELECT 1 FROM sqlite_master WHERE tbl_name='master_products' AND type='trigger'").fetchone():
        raise ValueError('Unexpected master trigger; review required')
    fk = conn.execute('PRAGMA foreign_keys').fetchone()[0]
    legacy = conn.execute('PRAGMA legacy_alter_table').fetchone()[0]
    try:
        conn.execute('PRAGMA foreign_keys=OFF')
        conn.execute('PRAGMA legacy_alter_table=ON')
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('ALTER TABLE master_products RENAME TO '+ARCHIVE)
        conn.execute(updated)
        conn.execute('INSERT INTO master_products SELECT * FROM '+ARCHIVE)
        for name, sql in indices:
            conn.execute(sql.replace(name, name+'_0043', 1))
        if conn.execute('SELECT * FROM master_products EXCEPT SELECT * FROM '+ARCHIVE).fetchone() or conn.execute('SELECT * FROM '+ARCHIVE+' EXCEPT SELECT * FROM master_products').fetchone():
            raise ValueError('Existing master values changed')
        if conn.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Foreign key violation')
        conn.execute('INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)', ('0043','nullable_master_unit_pack',checksum,now))
        conn.commit()
    except Exception:
        if conn.in_transaction: conn.rollback()
        raise
    finally:
        conn.execute('PRAGMA legacy_alter_table='+str(legacy))
        conn.execute('PRAGMA foreign_keys='+str(fk))
    return True


def rollback(conn):
    """Restore original constraints only before later master writes.

    Refuse any new/changed masters; preserve forward table, never discard data.
    After import use application/visibility rollback, retaining nullable schema.
    """
    if conn.in_transaction: raise ValueError('Rollback requires its own transaction')
    fk=conn.execute('PRAGMA foreign_keys').fetchone()[0]
    legacy=conn.execute('PRAGMA legacy_alter_table').fetchone()[0]
    try:
        conn.execute('PRAGMA foreign_keys=OFF');conn.execute('PRAGMA legacy_alter_table=ON');conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT * FROM master_products EXCEPT SELECT * FROM '+ARCHIVE).fetchone() or conn.execute('SELECT * FROM '+ARCHIVE+' EXCEPT SELECT * FROM master_products').fetchone():
            raise ValueError('Later master writes prevent constraint rollback; retain nullable schema')
        conn.execute('ALTER TABLE master_products RENAME TO _forward_0043_master_products')
        conn.execute('ALTER TABLE '+ARCHIVE+' RENAME TO master_products')
        if conn.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Foreign key violation')
        # Retain the migration ledger and forward archive for audited rollback.
        conn.commit()
    except Exception:
        if conn.in_transaction:conn.rollback()
        raise
    finally:
        conn.execute('PRAGMA legacy_alter_table='+str(legacy));conn.execute('PRAGMA foreign_keys='+str(fk))
