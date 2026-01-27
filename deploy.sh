#!/bin/bash

APP_DIR="/opt/heappe/heappe-admin-app"
SERVICE_NAME="adminpanel"
LOG_FILE="/var/log/deploy_${SERVICE_NAME}.log"
VENV_PYTHON="${APP_DIR}/venv/bin/python"
PIP_COMMAND="${APP_DIR}/venv/bin/pip"

GIT_URL=${GIT_URL}
GIT_TAG=${GIT_TAG:-"testing"}
GIT_USER=${GIT_USER}
GIT_PASS=${GIT_PASS}

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

cleanup() {
    if [ "$REMOTE_CHANGED" = true ] && [ -n "$ORIGINAL_URL" ]; then
        cd "$APP_DIR" 2>/dev/null
        git remote set-url origin "$ORIGINAL_URL" 2>/dev/null
    fi
    unset GIT_PASS AUTH_URL ENCODED_PASS
}

check_error() {
    if [ $? -ne 0 ]; then
        log "ERROR: Step failed. Exiting."
        cleanup
        exit 1
    fi
}

trap cleanup EXIT

log "=== START DEPLOYMENT: $GIT_TAG ==="

cd "$APP_DIR"
check_error

ORIGINAL_URL=$(git remote get-url origin 2>/dev/null)

if [ "$GIT_URL" = "origin" ] || [ -z "$GIT_URL" ]; then
    GIT_URL="$ORIGINAL_URL"
fi

REMOTE_CHANGED=false

if [ -n "$GIT_USER" ] && [ -n "$GIT_PASS" ] && [ -n "$GIT_URL" ] && [ "$GIT_URL" != "origin" ]; then
    ENCODED_PASS=$(echo -n "$GIT_PASS" | curl -s -o /dev/null -w "%{url_effective}" --get --data-urlencode "=@-" "" | cut -c 3-)
    AUTH_URL=$(echo "$GIT_URL" | sed "s|//|//${GIT_USER}:${ENCODED_PASS}@|")
    git remote set-url origin "$AUTH_URL"
    check_error
    REMOTE_CHANGED=true
fi
git fetch origin --tags --force --prune >> "$LOG_FILE" 2>&1
check_error

if git rev-parse --verify "origin/$GIT_TAG" >/dev/null 2>&1; then
    TARGET="origin/$GIT_TAG"
else
    TARGET="$GIT_TAG"
fi

git checkout -f "$GIT_TAG" >> "$LOG_FILE" 2>&1 || git checkout -b "$GIT_TAG" "$TARGET" >> "$LOG_FILE" 2>&1
git reset --hard "$TARGET" >> "$LOG_FILE" 2>&1
git clean -fd >> "$LOG_FILE" 2>&1
check_error

if [ -f "requirements.txt" ]; then
    $PIP_COMMAND install -r requirements.txt >> "$LOG_FILE" 2>&1
    check_error
fi

$VENV_PYTHON manage.py migrate --noinput >> "$LOG_FILE" 2>&1
check_error

sudo systemctl restart "$SERVICE_NAME"
check_error

sleep 5
if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    log "=== SUCCESS ==="
else
    log "FAILED"
    sudo journalctl -u "$SERVICE_NAME" -n 50 --no-pager >> "$LOG_FILE"
    exit 1
fi

exit 0