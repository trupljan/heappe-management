#!/bin/bash

APP_DIR="/opt/heappe/heappe-admin-app"
SERVICE_NAME="adminpanel"
LOG_FILE="/var/log/deploy_${SERVICE_NAME}.log"
VENV_PYTHON="/opt/heappe/venv/bin/python"
PIP_COMMAND="/opt/heappe/venv/bin/pip"

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a $LOG_FILE
}

check_error() {
    if [ $? -ne 0 ]; then
        log "ERROR: Step failed: $1"
        exit 1
    fi
}

log "--- DEPLOYMENT STARTED ---"

GIT_URL=${GIT_URL}
GIT_TAG=${GIT_TAG:-"testing"}
GIT_USER=${GIT_USER}
GIT_PASS=${GIT_PASS}

cd $APP_DIR
check_error "cd $APP_DIR"

if [ -n "$GIT_USER" ] && [ -n "$GIT_PASS" ]; then
    AUTH_URL=$(echo "$GIT_URL" | sed "s|//|//${GIT_USER}:${GIT_PASS}@|")
else
    AUTH_URL="$GIT_URL"
fi

git fetch "$AUTH_URL" --tags --force
check_error "git fetch"

if git show-ref --quiet "refs/tags/$GIT_TAG"; then
    RESET_REF="$GIT_TAG"
else
    RESET_REF="origin/$GIT_TAG"
fi

git reset --hard "$RESET_REF"
check_error "git reset $RESET_REF"

if [ -f "requirements.txt" ]; then
    $PIP_COMMAND install -r requirements.txt
    check_error "pip install"
fi

$VENV_PYTHON manage.py migrate --noinput
check_error "django migrate"

$VENV_PYTHON manage.py collectstatic --noinput
check_error "django collectstatic"

sudo systemctl restart $SERVICE_NAME
check_error "systemctl restart"

sleep 5
if sudo systemctl is-active --quiet $SERVICE_NAME; then
    log "--- DEPLOYMENT SUCCESS ---"
else
    log "--- DEPLOYMENT FAILED (Service not running) ---"
    exit 1
fi

unset GIT_PASS AUTH_URL
exit 0