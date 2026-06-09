#!/usr/bin/env bash
# ============================================================================
# Auto-deploy для PRODUCTION (srv-technik1:8765)
# ============================================================================
# Запускается cron'ом каждые 5 минут.
# Если на origin/main есть новые коммиты — git pull + restart сервиса.
#
# Защита:
#   - Только в ветке main
#   - Только если remote head отличается от local
#   - С health-check после restart (если упал — откат к предыдущему коммиту)
#
# Логи: storage/cron-prod.log + systemd journal
# ============================================================================

set -euo pipefail

PROJECT_DIR="/home/andy/meeting-protocol"
SERVICE_NAME="meeting-protocol.service"
LOG_FILE="$PROJECT_DIR/storage/cron-prod.log"
HEALTH_URL="http://127.0.0.1:8765/api/v1/health"
HEALTH_TIMEOUT=15
DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

log() {
    echo "[$DATE] $*" | tee -a "$LOG_FILE"
}

cd "$PROJECT_DIR"

# === Guard 1: должны быть в main ===
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "main" ]; then
    log "SKIP: not on main (current: $CURRENT_BRANCH)"
    exit 0
fi

# === Guard 2: чистота рабочей директории ===
if ! git diff --quiet HEAD 2>/dev/null; then
    log "SKIP: uncommitted local changes"
    exit 0
fi

# === Проверяем remote ===
git fetch origin main --quiet 2>&1 || { log "ERROR: git fetch failed"; exit 1; }

LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git rev-parse origin/main)

if [ "$LOCAL_SHA" = "$REMOTE_SHA" ]; then
    # Нет новых коммитов — тишина
    exit 0
fi

log "============================================================"
log "DEPLOY START: $LOCAL_SHA -> $REMOTE_SHA"
log "  commit: $(git log -1 --format='%h %s' origin/main)"

# === Сохраняем pre-deploy SHA (для rollback) ===
PRE_DEPLOY_SHA="$LOCAL_SHA"
log "  pre-deploy SHA (for rollback): $PRE_DEPLOY_SHA"

# === Pull + install ===
if ! git pull --ff-only origin main 2>&1 | tee -a "$LOG_FILE"; then
    log "ERROR: git pull failed, leaving in pre-deploy state"
    exit 1
fi

# pip install --quiet чтобы не спамить (новые deps бывают редко)
if ! pip install -q -r requirements.txt 2>&1 | tail -3 | tee -a "$LOG_FILE"; then
    log "WARN: pip install had issues (continuing anyway)"
fi

# === Restart сервиса ===
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
if ! systemctl --user restart "$SERVICE_NAME" 2>&1 | tee -a "$LOG_FILE"; then
    log "ERROR: systemctl restart failed — rolling back to $PRE_DEPLOY_SHA"
    git reset --hard "$PRE_DEPLOY_SHA" 2>&1 | tee -a "$LOG_FILE"
    exit 1
fi

# === Health check (до 15 сек) ===
log "  waiting for service to be healthy..."
HEALTHY=false
for i in $(seq 1 $HEALTH_TIMEOUT); do
    if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
        HEALTHY=true
        break
    fi
    sleep 1
done

if [ "$HEALTHY" = "true" ]; then
    NEW_SHA=$(git rev-parse --short HEAD)
    log "✓ DEPLOY OK: $NEW_SHA is live"
    log "============================================================"
    exit 0
else
    log "ERROR: health check failed after ${HEALTH_TIMEOUT}s — rolling back to $PRE_DEPLOY_SHA"
    # Откат
    git reset --hard "$PRE_DEPLOY_SHA" 2>&1 | tee -a "$LOG_FILE"
    systemctl --user restart "$SERVICE_NAME" 2>&1 | tee -a "$LOG_FILE"
    log "✗ DEPLOY FAILED, rolled back"
    log "============================================================"
    # Возвращаем non-zero, чтобы cron-логгеры заметили
    exit 2
fi
