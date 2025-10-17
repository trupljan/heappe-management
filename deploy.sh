#!/bin/bash

# ==============================================================================
# DJANGO GUNICORN FULL DEPLOYMENT SCRIPT (SIMPLIFIED VERSION)
#
# This script performs a code update via Git and restarts the systemd service.
# NOTE: VENV rebuild and Django commands (migrate, collectstatic) are removed.
# ==============================================================================

# --- CONFIGURATION ---
APP_DIR="/opt/heappe/heappe-admin-app"
SERVICE_NAME="adminpanel"
LOG_FILE="/var/log/deploy_${SERVICE_NAME}.log"
PYTHON_BIN="python3" # Ensure this path is correct for your system
# =====================

# Function for timestamped logging
log() {
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

log "--- DEPLOYMENT STARTED ---"

# 1. Change Directory
log "Changing directory to $APP_DIR..."
cd $APP_DIR
check_error "Change directory"

# 2. Code Update from Git
log "Pulling latest code from Git..."
git pull
check_error "Git pull"

# 3. Restart Service (Assumes service is already stopped or can handle graceful reload)
log "Restarting the $SERVICE_NAME service..."
sudo systemctl restart $SERVICE_NAME
check_error "Restart service"

# 4. Status Check and Logging
log "Waiting 5 seconds and checking service status..."
sleep 5
sudo systemctl status $SERVICE_NAME | grep "Active:" | tee -a $LOG_FILE

# 5. Revert Deployment Script to ensure clean state for next run
log "Reverting deployment script to committed state..."
git checkout deployment_script.sh
check_error "Git checkout deployment script"

log "--- DEPLOYMENT SUCCESSFULLY COMPLETED 🎉 ---"
log "Check full logs with: journalctl -u ${SERVICE_NAME}.service"

exit 0
