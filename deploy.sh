#!/bin/bash

# ==============================================================================
# DJANGO GUNICORN FULL DEPLOYMENT SCRIPT (DYNAMIC VERSION)
# Safe method: git fetch followed by git reset --hard
# ==============================================================================

# --- CONFIGURATION ---
APP_DIR="/opt/heappe/heappe-admin-app"
SERVICE_NAME="adminpanel"
LOG_FILE="/var/log/deploy_${SERVICE_NAME}.log"
# --- ENVIRONMENT SPECIFIC COMMANDS ---
# Doplnil jsem standardní kroky pro Django (instalace, migrace)
VENV_PYTHON="/path/to/your/venv/bin/python" # ZMĚŇTE NA CESTU K VAŠEMU PYTHONU VE VIRTUAL ENV
PIP_COMMAND="/path/to/your/venv/bin/pip"    # ZMĚŇTE NA CESTU K VAŠEMU PIPU VE VIRTUAL ENV
# =====================================

# Function for timestamped logging
log() {
    # DO NOT LOG THE PASSWORD
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a $LOG_FILE
}

# Function to check the return code of the last command
check_error() {
    if [ $? -ne 0 ]; then
        log "ERROR: Step failed: $1"
        log "Deployment ABORTED."
        exit 1
    fi
}

log "--- DYNAMIC DEPLOYMENT STARTED ---"

# 1. Retrieve Variables from Environment
GIT_URL=$GIT_URL
GIT_TAG=$GIT_TAG
GIT_USER=$GIT_USER
GIT_PASS=$GIT_PASS

log "Deployment Target: URL=${GIT_URL}, Reference=${GIT_TAG}"

# 2. Change Directory
log "Changing directory to $APP_DIR..."
cd $APP_DIR
check_error "Change directory to $APP_DIR"

# 3. Code Update from Git (Securely using credentials)
# Construct the authenticated URL for HTTPS access
if [ -n "$GIT_USER" ] && [ -n "$GIT_PASS" ]; then
    # Format: https://username:password@domain/repo.git
    AUTH_URL=$(echo "$GIT_URL" | sed "s|//|//${GIT_USER}:${GIT_PASS}@|")
else
    AUTH_URL="$GIT_URL"
fi

log "Fetching all remote references from authenticated repository..."

# Safely fetch all references (no merge, just update local references)
git fetch "$AUTH_URL"
check_error "Git fetch failed. Check credentials/URL."

# 4. Checkout and Reset (The safer deployment method)
# Resetuje HEAD na přesný stav vzdálené reference (např. origin/main nebo tag v1.0.0)
log "Resetting local repository state to reference: $GIT_TAG..."

# Check if GIT_TAG is a branch (by checking origin/) or a simple tag
if git show-ref --quiet "refs/heads/$GIT_TAG"; then
    # It's a local branch, use origin/branch_name to reset
    RESET_REF="origin/$GIT_TAG"
else
    # Assume it's a tag or remote branch that has been fetched
    RESET_REF="$GIT_TAG"
fi

git reset --hard "$RESET_REF"
check_error "Git reset --hard $GIT_TAG"

# 5. Environment and Database Updates (Django Specific)
log "Installing/Updating Python dependencies..."
$PIP_COMMAND install -r requirements.txt --upgrade
check_error "Dependency update (pip install)"

log "Running database migrations..."
$VENV_PYTHON manage.py migrate --noinput
check_error "Database migrations"

log "Collecting static files..."
$VENV_PYTHON manage.py collectstatic --noinput
check_error "Collecting static files"

# 6. Service Restart
log "Restarting the $SERVICE_NAME service..."
sudo systemctl restart $SERVICE_NAME
check_error "Restart service $SERVICE_NAME"

# 7. Revert Deployment Script (Good security practice if the script itself is in the repo)
log "Reverting deployment script to committed state..."
git checkout "$0"
# Ignoring check_error here, as the script might not be named 'deployment_script.sh'
# and we don't want to fail deployment if this fails.

# 8. Status Check and Logging
log "Waiting 5 seconds and checking service status..."
sleep 5
# Použijeme grep -q pro tichou kontrolu a logneme výstup jen pro informaci
STATUS_OUTPUT=$(sudo systemctl status $SERVICE_NAME | grep "Active:")
echo "$STATUS_OUTPUT" | tee -a $LOG_FILE

if echo "$STATUS_OUTPUT" | grep -q "active (running)"; then
    log "Service $SERVICE_NAME is RUNNING."
else
    log "WARNING: Service $SERVICE_NAME is NOT running. Check system logs."
fi

# 9. Clean up environment variables
unset GIT_URL GIT_TAG GIT_USER GIT_PASS

log "--- DYNAMIC DEPLOYMENT SUCCESSFULLY COMPLETED 🎉 ---"
log "Check full logs with: journalctl -u ${SERVICE_NAME}.service"

exit 0
