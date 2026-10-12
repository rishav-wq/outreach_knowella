#!/usr/bin/env bash
# Nightly backup of the outreach database (campaigns, leads, drafts, decisions and,
# critically, the do-not-contact list). Keeps the newest 14. Install on the VM:
#   sudo crontab -e   →   15 2 * * * /opt/outreach-agent/deploy/backup.sh >> /var/log/outreach-backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."

DIR=${BACKUP_DIR:-/var/backups/outreach}
mkdir -p "$DIR"
STAMP=$(date +%Y%m%d-%H%M)
OUT="$DIR/outreach-$STAMP.archive.gz"

# Docker reads .env itself, exactly as the app container does. (Loading it with bash's
# `source` broke on values like `Name <address>`, so no backup ever ran.)
if ! docker run --rm --env-file .env mongo:6 \
    sh -c 'exec mongodump --uri "$MONGO_URI" --db "${MONGO_DB:-outreach}" --archive --gzip --quiet' \
    > "$OUT.part"; then
  rm -f "$OUT.part"
  echo "backup FAILED: mongodump could not dump the database at $(date)" >&2
  exit 1
fi

# Only a complete, non-empty dump counts: a failed run must never push a good backup
# out of the rotation below.
if [ ! -s "$OUT.part" ] || ! gzip -t "$OUT.part" 2>/dev/null; then
  rm -f "$OUT.part"
  echo "backup FAILED: empty or corrupt dump at $(date)" >&2
  exit 1
fi
mv "$OUT.part" "$OUT"

# rotate: keep the newest 14
ls -1t "$DIR"/outreach-*.archive.gz | tail -n +15 | xargs -r rm --
echo "backup ok: $OUT ($(du -h "$OUT" | cut -f1))"
