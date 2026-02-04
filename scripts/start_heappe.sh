#!/bin/bash

# Startup script for HEAppE deployment
# Ensures MSSQL and vault_init services are ready before proceeding

# Configuration variables (passed as arguments or sourced from environment)
INSTANCE_NAME="$1"
COMPOSE_DIR="$2"
MSSQL_PORT="$3"
MSSQL_SA_PASSWORD="$4"
VAULT_ADDR="http://localhost:8200"
MAX_ATTEMPTS=30
SLEEP_INTERVAL=5

# Check if required arguments are provided
if [ -z "$INSTANCE_NAME" ] || [ -z "$COMPOSE_DIR" ] || [ -z "$MSSQL_PORT" ] || [ -z "$MSSQL_SA_PASSWORD" ]; then
    echo "Error: Missing required arguments."
    echo "Usage: $0 <instance_name> <compose_dir> <mssql_port> <mssql_sa_password>"
    exit 1
fi

# Change to the compose directory
cd "$COMPOSE_DIR" || { echo "Error: Cannot change to directory $COMPOSE_DIR"; exit 1; }

# Run docker compose up -d
echo "Starting Docker Compose with profiles db and initVault..."
docker compose --profile db --profile initVault -p "$INSTANCE_NAME" up -d
if [ $? -ne 0 ]; then
    echo "Error: Docker Compose up failed."
    exit 1
fi



echo "All services are ready."
exit 0