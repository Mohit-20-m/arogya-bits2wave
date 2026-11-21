#!/usr/bin/env bash
# PostgreSQL backups with pgBackRest (full | incr | info | check).  Restore: see README → Backups.
# Schedule on the server (crontab -e, times in the server's time zone):
#   15 2 * * 0   /home/ubuntu/arogya/ops/backup.sh full >> /home/ubuntu/backup.log 2>&1   # weekly full
#   15 2 * * 1-6 /home/ubuntu/arogya/ops/backup.sh incr >> /home/ubuntu/backup.log 2>&1   # nightly incremental
# Tested on 2026-11-21: full backup, `pgbackrest verify` OK and a file-level restore into a scratch folder OK.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec -T -u postgres postgres oralscreen-backup "${1:-full}"
