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
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a $LOG_FILE
}

check_error() {
    if [ $? -ne 0 ]; then
        log "ERROR: Step failed. Exiting."
        exit 1
    fi
}

log "START: $GIT_TAG"

cd $APP_DIR
check_error

if [ -n "$GIT_USER" ] && [ -n "$GIT_PASS" ]; then
    ENCODED_PASS=$(echo -n "$GIT_PASS" | curl -s -o /dev/null -w "%{url_effective}" --get --data-urlencode "=@-" "" | cut -c 3-)
    AUTH_URL=$(echo "$GIT_URL" | sed "s|//|//${GIT_USER}:${ENCODED_PASS}@|")
else
    AUTH_URL="$GIT_URL"
fi

git fetch "$AUTH_URL" --tags --force --prune
check_error

if git rev-parse --verify "origin/$GIT_TAG" >/dev/null 2>&1; then
    TARGET="origin/$GIT_TAG"
else
    TARGET="$GIT_TAG"
fi

log "Target: $TARGET"
git reset --hard "$TARGET"
check_error

log "Commit: $(git rev-parse HEAD)"

if [ -f "requirements.txt" ]; then
    $PIP_COMMAND install -r requirements.txt >> $LOG_FILE 2>&1
    check_error
fi

$VENV_PYTHON manage.py migrate --noinput >> $LOG_FILE 2>&1
check_error

sudo systemctl restart $SERVICE_NAME
check_error

sleep 5
if sudo systemctl is-active --quiet $SERVICE_NAME; then
    log "SUCCESS"
else
    log "FAILED: Service not active"
    sudo journalctl -u $SERVICE_NAME -n 20 --no-pager >> $LOG_FILE
    exit 1
fi

unset GIT_PASS AUTH_URL ENCODED_PASS
exit 0