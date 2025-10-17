#!/bin/bash

# ==============================================================================
# DJANGO GUNICORN FULL DEPLOYMENT SCRIPT
#
# This script performs a code update via Git, a complete virtual environment
# rebuild, runs Django commands, and restarts the systemd service.
#
# FIX: Changed 'disable --now' to 'stop' in step 3 to prevent the script
# from self-terminating if it is executed by a process managed by this service.
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

# 3. Stop Current Service (FIXED: Use 'stop' instead of 'disable --now')
# This is necessary before deleting the VENV to avoid conflicts but must
# not terminate the running script if the service launched it.
log "Stopping the $SERVICE_NAME service..."
sudo systemctl stop $SERVICE_NAME
check_error "Stop service"

# 4. Reload Systemd Daemon Configuration
# Important if the service file was modified
log "Reloading systemd daemon configuration..."
sudo systemctl daemon-reload
check_error "Systemd daemon-reload"

# 5. Delete and Reinstall Virtual Environment (Hard Refresh)
# This ensures a clean slate, avoiding dependency issues.
if [ -d "venv" ]; then
    log "Removing old virtual environment (venv)..."
    rm -rf venv
    check_error "Remove venv"
fi

log "Creating a new virtual environment and installing dependencies..."
$PYTHON_BIN -m venv venv
check_error "Create venv"

source venv/bin/activate
check_error "Activate venv"

pip install -r requirements.txt
check_error "Install Python dependencies (pip)"

# 6. Run Django Commands
log "Running database migrations..."
python manage.py migrate --noinput
check_error "Django Migrate"

log "Collecting static files (collectstatic)..."
python manage.py collectstatic --noinput
check_error "Django Collectstatic"
deactivate # Deactivate VENV after usage

# 7. Restart Service (Cleaned up: only 'restart' is needed)
log "Restarting the $SERVICE_NAME service..."
sudo systemctl restart $SERVICE_NAME
check_error "Restart service"

# 8. Status Check and Logging
log "Waiting 5 seconds and checking service status..."
sleep 5
sudo systemctl status $SERVICE_NAME | grep "Active:" | tee -a $LOG_FILE

log "--- DEPLOYMENT SUCCESSFULLY COMPLETED 🎉 ---"
log "Check full logs with: journalctl -u ${SERVICE_NAME}.service"

exit 0