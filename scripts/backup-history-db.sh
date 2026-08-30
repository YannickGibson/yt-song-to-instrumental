#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

DB_FILE="data/history.db"
BACKUP_DIR="data/backups"
KEEP=7

if [ ! -f "$DB_FILE" ]; then
    echo "no $DB_FILE — nothing to back up"
    exit 0
fi

mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="$BACKUP_DIR/history-${TIMESTAMP}.db"

SRC="$DB_FILE" DST="$BACKUP_FILE" python3 - <<'PYEOF'
import os, sqlite3
src = sqlite3.connect(os.environ["SRC"])
dst = sqlite3.connect(os.environ["DST"])
with dst:
    src.backup(dst)
src.close()
dst.close()
PYEOF

ls -1t "$BACKUP_DIR"/history-*.db 2>/dev/null \
    | tail -n +$((KEEP + 1)) \
    | xargs -r rm -f

echo "backup: $BACKUP_FILE"
