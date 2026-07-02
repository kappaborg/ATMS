#!/usr/bin/env bash
# Postgres backup with rotation for the ATMS stack.
#
# Dumps the database from the atms-postgres container (or a direct host
# connection when POSTGRES_HOST is set and no container is running) into
# BACKUP_DIR, gzip-compressed, and prunes backups older than RETENTION_DAYS.
#
# Usage:
#   ./scripts/backup_postgres.sh                  # defaults
#   BACKUP_DIR=/mnt/backups RETENTION_DAYS=30 ./scripts/backup_postgres.sh
#
# Schedule it (host cron example, daily at 02:30):
#   30 2 * * * cd /path/to/Traffic && ./scripts/backup_postgres.sh >> logs/backup.log 2>&1
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-${REPO_ROOT}/backups/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
CONTAINER="${POSTGRES_CONTAINER:-atms-postgres}"

# Load DB settings from .env if present (never echoed).
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

DB="${POSTGRES_DB:-atms}"
USER="${POSTGRES_USER:-atms_user}"

mkdir -p "${BACKUP_DIR}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="${BACKUP_DIR}/${DB}_${STAMP}.sql.gz"

if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "${CONTAINER}"; then
  echo "Backing up ${DB} from container ${CONTAINER} -> ${OUT}"
  docker exec "${CONTAINER}" pg_dump -U "${USER}" -d "${DB}" --no-owner | gzip > "${OUT}"
elif command -v pg_dump >/dev/null 2>&1; then
  echo "Backing up ${DB} from ${POSTGRES_HOST:-localhost}:${POSTGRES_PORT:-5432} -> ${OUT}"
  PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump \
    -h "${POSTGRES_HOST:-localhost}" -p "${POSTGRES_PORT:-5432}" \
    -U "${USER}" -d "${DB}" --no-owner | gzip > "${OUT}"
else
  echo "ERROR: neither container '${CONTAINER}' is running nor pg_dump is installed" >&2
  exit 1
fi

# Fail loudly on empty dumps (a zero-byte backup is worse than none —
# it looks like coverage you don't have).
if [[ ! -s "${OUT}" ]] || [[ "$(gzip -l "${OUT}" | awk 'NR==2 {print $2}')" -eq 0 ]]; then
  rm -f "${OUT}"
  echo "ERROR: dump was empty, backup removed" >&2
  exit 1
fi

echo "Backup complete: ${OUT} ($(du -h "${OUT}" | cut -f1))"

# Rotation
DELETED=$(find "${BACKUP_DIR}" -name "${DB}_*.sql.gz" -mtime +"${RETENTION_DAYS}" -print -delete | wc -l | tr -d ' ')
echo "Rotation: removed ${DELETED} backup(s) older than ${RETENTION_DAYS} days"
