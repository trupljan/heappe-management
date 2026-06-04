#!/bin/bash
BASE_DIR="/opt/heappe/heappe-admin-app"
GIT_TAG=${GIT_TAG:-"main"}
APP_DIR="${BASE_DIR}/branches/main"
SERVICE_NAME="adminpanel"
LOG_FILE="/var/log/deploy_${SERVICE_NAME}.log"
STATIC_ROOT_DIR="${BASE_DIR}/static"


VENV_DIR="${BASE_DIR}/branches/.venv-main"
VENV_PYTHON="${VENV_DIR}/bin/python"
PIP_COMMAND="${VENV_DIR}/bin/pip"
GIT_URL=${GIT_URL:-"origin"}
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

if [ ! -d "$APP_DIR" ]; then
    log "ERROR: Directory $APP_DIR does not exist."
    exit 1
fi

cd "$APP_DIR"
check_error

ORIGINAL_URL=$(git remote get-url origin 2>/dev/null)
REMOTE_CHANGED=false

if [ -n "$GIT_USER" ] && [ -n "$GIT_PASS" ] && [ "$GIT_URL" != "origin" ]; then
    ENCODED_PASS=$(echo -n "$GIT_PASS" | curl -s -o /dev/null -w "%{url_effective}" --get --data-urlencode "=@-" "" | cut -c 3-)
    AUTH_URL=$(echo "$GIT_URL" | sed "s|//|//${GIT_USER}:${ENCODED_PASS}@|")
    git remote set-url origin "$AUTH_URL"
    check_error
    REMOTE_CHANGED=true
fi

git fetch origin --tags --prune >> "$LOG_FILE" 2>&1
git fetch origin "+refs/heads/*:refs/remotes/origin/*" --force >> "$LOG_FILE" 2>&1
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
    $PIP_COMMAND install --upgrade pip >> "$LOG_FILE" 2>&1
    $PIP_COMMAND install -r requirements.txt >> "$LOG_FILE" 2>&1
    check_error
fi

$VENV_PYTHON manage.py migrate --noinput >> "$LOG_FILE" 2>&1
check_error

mkdir -p "$STATIC_ROOT_DIR"
$VENV_PYTHON manage.py collectstatic --noinput --clear >> "$LOG_FILE" 2>&1 || log "WARNING: collectstatic failed"

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