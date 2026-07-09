#!/usr/bin/env bash
# Nightly backup of the outreach database (leads, drafts, decisions, and — critically —
# the do-not-contact list). Keeps 14 days. Install on the VM:
#   crontab -e   →   15 2 * * * /opt/outreach-agent/deploy/backup.sh >> /var/log/outreach-backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

DIR=${BACKUP_DIR:-/var/backups/outreach}
mkdir -p "$DIR"
STAMP=$(date +%Y%m%d-%H%M)

docker run --rm mongo:6 mongodump \
  --uri "$MONGO_URI" --db "${MONGO_DB:-outreach}" --archive --gzip \
  > "$DIR/outreach-$STAMP.archive.gz"

# rotate: keep the newest 14
ls -1t "$DIR"/outreach-*.archive.gz | tail -n +15 | xargs -r rm --
echo "backup ok: $DIR/outreach-$STAMP.archive.gz ($(du -h "$DIR/outreach-$STAMP.archive.gz" | cut -f1))"
