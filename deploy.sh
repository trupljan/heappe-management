#!/bin/bash

# ==============================================================================
# DJANGO GUNICORN FULL DEPLOYMENT SCRIPT (DYNAMIC VERSION)
# ==============================================================================

# --- CONFIGURATION ---
APP_DIR="/opt/heappe/heappe-admin-app"
SERVICE_NAME="adminpanel"
LOG_FILE="/var/log/deploy_${SERVICE_NAME}.log"
# =====================

# Function for timestamped logging
log() {
    # DO NOT LOG THE PASSWORD
    # The 'tee' command writes to both stdout (for the Python Popen pipe) and the log file
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
# NOTE: The credentials are NOT logged as they are used only to construct the URL.
GIT_URL=$GIT_URL
GIT_TAG=$GIT_TAG
GIT_USER=$GIT_USER
GIT_PASS=$GIT_PASS

log "Deployment Target: URL=${GIT_URL}, Tag=${GIT_TAG}"

# 2. Change Directory
log "Changing directory to $APP_DIR..."
cd $APP_DIR
check_error "Change directory"

# 3. Code Update from Git (Securely using credentials)
# Construct the authenticated URL: https://username:password@git.example.com/repo.git
# NOTE: This only works for HTTPS URLs. For SSH, you would need different setup (e.g., agent forwarding).
AUTH_URL=$(echo "$GIT_URL" | sed "s|//|//${GIT_USER}:${GIT_PASS}@|")

log "Fetching latest code from authenticated repository..."

# Use the authenticated URL to fetch all updates
git fetch "$AUTH_URL"
check_error "Git fetch"

# 4. Checkout the specific tag/branch
log "Checking out tag/branch: $GIT_TAG..."
git checkout "$GIT_TAG"
check_error "Git checkout $GIT_TAG"

# 5. Service Restart (Same as original)
log "Restarting the $SERVICE_NAME service..."
# Perform the necessary deployment steps here (e.g., venv setup, migrations, etc.)
# For this example, we keep only the restart
sudo systemctl restart $SERVICE_NAME
check_error "Restart service"

# 6. Status Check and Logging
log "Waiting 5 seconds and checking service status..."
sleep 5
sudo systemctl status $SERVICE_NAME | grep "Active:" | tee -a $LOG_FILE

# 7. Clean up environment variables (optional but good practice)
unset GIT_URL GIT_TAG GIT_USER GIT_PASS

log "--- DYNAMIC DEPLOYMENT SUCCESSFULLY COMPLETED 🎉 ---"
log "Check full logs with: journalctl -u ${SERVICE_NAME}.service"

exit 0