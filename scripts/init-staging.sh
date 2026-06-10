#!/usr/bin/env bash
# ============================================================================
# Init STAGING: создаёт копию проекта в /home/andy/meeting-protocol-staging
# ============================================================================
# Запускать ОДИН РАЗ перед первым деплоем staging.
# Копирует код, настраивает отдельный venv, отдельный systemd unit.
#
# После init:
#   - Запустить вручную: bash auto-deploy-staging.sh
#   - Или подождать 5 мин (cron)
# ============================================================================

set -euo pipefail

SOURCE_DIR="/home/andy/meeting-protocol"
STAGING_DIR="/home/andy/meeting-protocol-staging"
SERVICE_NAME="meeting-protocol-staging"
DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "[$DATE] === Init STAGING ==="

# === 1. Clone репо в отдельную папку ===
if [ -d "$STAGING_DIR" ]; then
    echo "STAGING_DIR already exists: $STAGING_DIR"
    echo "If you want to reinit, rm -rf $STAGING_DIR first"
    exit 1
fi

echo "Cloning $SOURCE_DIR -> $STAGING_DIR"
git clone "$SOURCE_DIR" "$STAGING_DIR"

cd "$STAGING_DIR"

# === 2. Switch to develop ===
git checkout develop 2>&1 || git checkout -b develop origin/develop

# === 3. Создаём отдельный venv (ОПЦИОНАЛЬНО — у нас нет python3-venv) ===
# На srv-technik1 системный /usr/bin/python3 уже имеет все зависимости (prod использует его).
# Поэтому staging тоже использует system python — без venv.
if [ ! -d .venv ] && [ -d /usr/lib/python3.12 ]; then
    if python3 -m venv .venv 2>/dev/null; then
        source .venv/bin/activate
        pip install --quiet --upgrade pip
        pip install --quiet -r requirements.txt
    else
        echo "WARN: python3-venv недоступен, используем /usr/bin/python3 напрямую (как prod)"
    fi
fi

# === 4. Создаём .env (наследует от prod, но с другими параметрами) ===
if [ ! -f .env ]; then
    echo "Creating .env from .env.example with staging-specific overrides"
    cp .env.example .env
    # Меняем порт на 8766 (staging)
    sed -i 's/^port=.*/port=8766/' .env || echo "port=8766" >> .env
    # Отключаем реальные API-ключи (для staging — фейк или те же)
    # По умолчанию используем те же ключи что в prod, если они заданы в /home/andy/.env-staging
    if [ -f /home/andy/.env-staging ]; then
        echo "Loading staging secrets from /home/andy/.env-staging"
        cat /home/andy/.env-staging >> .env
    fi
fi

# === 5. Создаём отдельный systemd --user unit ===
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"

cat > "$UNIT_DIR/$SERVICE_NAME.service" <<EOF
[Unit]
Description=Meeting Protocol STAGING (FastAPI + MCP, port 8766)
After=network.target

[Service]
Type=simple
WorkingDirectory=$STAGING_DIR
Environment=PYTHONUNBUFFERED=1
Environment=STORAGE_DIR=$STAGING_DIR/storage
Environment=PORT=8766
ExecStart=/usr/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8766 --log-level info
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

# === 6. Включаем и стартуем ===
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME.service"
systemctl --user start "$SERVICE_NAME.service"

sleep 3
if curl -fsS --max-time 5 "http://127.0.0.1:8766/api/v1/health" >/dev/null 2>&1; then
    echo "✓ STAGING started successfully on http://127.0.0.1:8766"
else
    echo "WARN: staging not responding yet, check journalctl --user -u $SERVICE_NAME"
fi

echo ""
echo "=== Next steps ==="
echo "1. Add Caddy block on srv-proxy (192.168.0.125) for staging-meeting-protocol.gluman.tech:4443 -> 192.168.0.114:8766"
echo "2. Add DNS A-record: staging-meeting-protocol.gluman.tech -> 5.227.60.54"
echo "3. Add cron job: */5 * * * * /home/andy/meeting-protocol/scripts/auto-deploy-staging.sh"
echo ""
echo "Done."
