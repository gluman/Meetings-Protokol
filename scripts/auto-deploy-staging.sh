#!/usr/bin/env bash
# ============================================================================
# Auto-deploy для STAGING (srv-technik1:8766)
# ============================================================================
# Запускается cron'ом каждые 5 минут.
# Если на origin/$STAGING_BRANCH (default: develop) есть новые коммиты — git pull + restart staging.
#
# Override: STAGING_BRANCH=feature/glossary-history-queue bash auto-deploy-staging.sh
# (для review-периода чтобы не мержить в develop пока LLM/UI ревью)
#
# Staging — отдельная копия сервиса на порту 8766:
#   - Working dir: /home/andy/meeting-protocol-staging
#   - venv:        НЕ используется (system /usr/bin/python3 как в prod)
#   - systemd --user unit: meeting-protocol-staging.service
#   - URL (LAN only): http://192.168.0.114:8766/
#   - НЕ пробрасывается на роутере — тестовый стенд, доступ только из LAN.
# ============================================================================

set -euo pipefail

STAGING_BRANCH="${STAGING_BRANCH:-develop}"
PROJECT_DIR="/home/andy/meeting-protocol-staging"
SOURCE_DIR="/home/andy/meeting-protocol"
SERVICE_NAME="meeting-protocol-staging.service"
LOG_FILE="$PROJECT_DIR/storage/cron-staging.log"
HEALTH_URL="http://127.0.0.1:8766/api/v1/health"
HEALTH_TIMEOUT=15
DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

log() {
    echo "[$DATE] [branch=$STAGING_BRANCH] $*" | tee -a "$LOG_FILE"
}

# === Проверяем, существует ли staging dir (создаётся при первом деплое) ===
if [ ! -d "$PROJECT_DIR/.git" ]; then
    log "STAGING NOT INITIALIZED. Run: bash $SOURCE_DIR/scripts/init-staging.sh"
    exit 0
fi

cd "$PROJECT_DIR"

CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "$STAGING_BRANCH" ]; then
    log "INFO: switching $CURRENT_BRANCH -> $STAGING_BRANCH (review mode)"
    git checkout "$STAGING_BRANCH" 2>&1 | head -1 | tee -a "$LOG_FILE" || {
        log "ERROR: git checkout $STAGING_BRANCH failed"; exit 1;
    }
fi

if ! git diff --quiet HEAD 2>/dev/null; then
    log "SKIP: uncommitted local changes"
    exit 0
fi

git fetch origin "$STAGING_BRANCH" --quiet 2>&1 || { log "ERROR: git fetch failed"; exit 1; }

LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git rev-parse "origin/$STAGING_BRANCH")

if [ "$LOCAL_SHA" = "$REMOTE_SHA" ]; then
    exit 0
fi

log "============================================================"
log "STAGING DEPLOY: $LOCAL_SHA -> $REMOTE_SHA"
log "  commit: $(git log -1 --format='%h %s' origin/$STAGING_BRANCH)"

PRE_DEPLOY_SHA="$LOCAL_SHA"

if ! git pull --ff-only "origin" "$STAGING_BRANCH" 2>&1 | tee -a "$LOG_FILE"; then
    log "ERROR: git pull failed"
    exit 1
fi

# Без venv — staging использует /usr/bin/python3 как prod
# (на srv-technik1 нет python3-venv, см. init-staging.sh)

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
if ! systemctl --user restart "$SERVICE_NAME" 2>&1 | tee -a "$LOG_FILE"; then
    log "ERROR: restart failed — rolling back"
    git reset --hard "$PRE_DEPLOY_SHA"
    exit 1
fi

log "  waiting for service..."
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
    log "✓ STAGING OK: $NEW_SHA"
    log "============================================================"
    exit 0
else
    log "ERROR: health check failed — rolling back"
    git reset --hard "$PRE_DEPLOY_SHA"
    systemctl --user restart "$SERVICE_NAME"
    log "✗ STAGING DEPLOY FAILED, rolled back"
    log "============================================================"
    exit 2
fi
