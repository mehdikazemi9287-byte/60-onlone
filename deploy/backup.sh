#!/bin/sh
# Daily backup (runs inside the `backup` service): PostgreSQL custom-format dump + media/documents archive.
# Keeps BACKUP_KEEP_DAYS locally; if BACKUP_RCLONE_REMOTE is set (e.g. "arvan:sixty-backups"), copies off-site too.
# Restore drill: docs/DEPLOY.md §6.
set -eu
STAMP=$(date -u +%Y%m%d-%H%M)
DIR=/backups
KEEP=${BACKUP_KEEP_DAYS:-14}
mkdir -p "$DIR"

echo "$(date -u) backup start"
pg_dump -Fc --no-owner -f "$DIR/db-$STAMP.dump.part"
pg_restore --list "$DIR/db-$STAMP.dump.part" >/dev/null   # the dump is readable, not just written
mv "$DIR/db-$STAMP.dump.part" "$DIR/db-$STAMP.dump"
tar -czf "$DIR/files-$STAMP.tar.gz.part" -C /data media documents 2>/dev/null || true
[ -f "$DIR/files-$STAMP.tar.gz.part" ] && mv "$DIR/files-$STAMP.tar.gz.part" "$DIR/files-$STAMP.tar.gz"

if [ -n "${BACKUP_RCLONE_REMOTE:-}" ] && command -v rclone >/dev/null 2>&1; then
  rclone copy "$DIR" "$BACKUP_RCLONE_REMOTE" --include "*-$STAMP.*" --config /backups/rclone.conf \
    && echo "off-site copy ok" || echo "OFF-SITE COPY FAILED"
fi

find "$DIR" -name 'db-*.dump' -mtime +"$KEEP" -delete
find "$DIR" -name 'files-*.tar.gz' -mtime +"$KEEP" -delete
echo "$(date -u) backup done: db-$STAMP.dump ($(du -h "$DIR/db-$STAMP.dump" | cut -f1))"
