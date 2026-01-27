#!/bin/bash

APP_DIR="/opt/heappe/heappe-admin-app"
SERVICE_NAME="adminpanel"
LOG_FILE="/var/log/deploy_${SERVICE_NAME}.log"
VENV_PYTHON="${APP_DIR}/venv/bin/python"
PIP_COMMAND="${APP_DIR}/venv/bin/pip"

# Tyto proměnné by měly být definovány prostředím (např. Jenkins/GitLab)
GIT_URL=${GIT_URL}
GIT_TAG=${GIT_TAG:-"testing"}
GIT_USER=${GIT_USER}
GIT_PASS=${GIT_PASS}

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a $LOG_FILE
}

check_error() {
    if [ $? -ne 0 ]; then
        log "ERROR: Step failed. Exiting."
        cleanup
        exit 1
    fi
}

# Funkce pro vyčištění citlivých údajů z git configu
cleanup() {
    log "Cleaning up git remote URL..."
    cd $APP_DIR
    git remote set-url origin "$GIT_URL" 2>/dev/null
    unset GIT_PASS AUTH_URL ENCODED_PASS
}

# Zachytit signály přerušení, aby se vždy provedl cleanup
trap cleanup EXIT

log "=== START DEPLOYMENT: $GIT_TAG ==="

cd $APP_DIR
check_error

# Sestavení AUTH_URL a dočasná aktualizace remote origin
if [ -n "$GIT_USER" ] && [ -n "$GIT_PASS" ]; then
    ENCODED_PASS=$(echo -n "$GIT_PASS" | curl -s -o /dev/null -w "%{url_effective}" --get --data-urlencode "=@-" "" | cut -c 3-)
    AUTH_URL=$(echo "$GIT_URL" | sed "s|//|//${GIT_USER}:${ENCODED_PASS}@|")

    log "Updating remote origin URL with credentials..."
    git remote set-url origin "$AUTH_URL"
    check_error
else
    AUTH_URL="$GIT_URL"
fi

log "Fetching latest data from origin..."
# Fetch nyní aktualizuje origin/branch díky správně nastavenému remote
git fetch origin --tags --force --prune >> $LOG_FILE 2>&1
check_error

# Určení cíle (priorita je origin/tag před lokálním tagem)
if git rev-parse --verify "origin/$GIT_TAG" >/dev/null 2>&1; then
    TARGET="origin/$GIT_TAG"
else
    TARGET="$GIT_TAG"
fi

log "Target commit/branch resolved to: $TARGET"

# Checkout a vyčištění
log "Checking out $GIT_TAG..."
git checkout -f "$GIT_TAG" >> $LOG_FILE 2>&1 || git checkout -b "$GIT_TAG" "$TARGET" >> $LOG_FILE 2>&1
git reset --hard "$TARGET" >> $LOG_FILE 2>&1
git clean -fd >> $LOG_FILE 2>&1
check_error

log "Current commit after reset: $(git rev-parse HEAD)"

# Instalace dependencí
if [ -f "requirements.txt" ]; then
    log "Installing requirements..."
    $PIP_COMMAND install -r requirements.txt >> $LOG_FILE 2>&1
    check_error
fi

# Migrace databáze
log "Running database migrations..."
$VENV_PYTHON manage.py migrate --noinput >> $LOG_FILE 2>&1
check_error

# Restart služby
log "Restarting service $SERVICE_NAME..."
sudo systemctl restart $SERVICE_NAME
check_error

# Kontrola stavu po 5 sekundách
sleep 5
if sudo systemctl is-active --quiet $SERVICE_NAME; then
    log "=== SUCCESS: Deployment finished ==="
else
    log "FAILED: Service not active!"
    sudo journalctl -u $SERVICE_NAME -n 50 --no-pager >> $LOG_FILE
    exit 1
fi

exit 0
