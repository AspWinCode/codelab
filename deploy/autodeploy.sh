#!/bin/bash
# Автодеплой Codelab по cron (каждую минуту), по образцу
# learning-portal/deploy/autodeploy.sh:
#   * * * * * /root/codelab/deploy/autodeploy.sh
#
# Держит боевой хост в актуальном состоянии с origin/main. flock не даёт
# пересечься с ручным `docker compose up` по SSH.

set -u

REPO_DIR="${REPO_DIR:-/root/codelab}"
LOCKFILE="/tmp/codelab-deploy.lock"
LOG="${AUTODEPLOY_LOG:-/var/log/codelab-autodeploy.log}"

log() { echo "$(date '+%F %T') $*" >>"$LOG"; }

exec 200>"$LOCKFILE"
if ! flock -n 200; then
  exit 0   # уже идёт деплой (cron или человек) — тихо выходим
fi

cd "$REPO_DIR" || { log "FATAL: no $REPO_DIR"; exit 1; }

git fetch origin main --quiet 2>>"$LOG"
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

compose() { docker compose "$@" >>"$LOG" 2>&1; }

if [ "$LOCAL" != "$REMOTE" ]; then
  log "deploying $REMOTE"
  git pull --ff-only origin main >>"$LOG" 2>&1
  compose up -d --build
  compose ps >>"$LOG" 2>&1
  log "done $REMOTE"
else
  # Самолечение: поднять всё, что упало/в Created/Exited. Дёшево, когда всё ок.
  compose up -d
fi
