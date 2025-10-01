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

# Check MSSQL readiness
echo "Checking MSSQL container ${INSTANCE_NAME}_mssql..."
for ((i=1; i<=MAX_ATTEMPTS; i++)); do
    # Check if container is running
    if docker ps -q -f name="${INSTANCE_NAME}_mssql" | grep -q .; then
        # Attempt to connect to MSSQL
        if docker exec "${INSTANCE_NAME}_mssql" /opt/mssql-tools/bin/sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -Q "SELECT 1" > /dev/null 2>&1; then
            echo "MSSQL is ready."
            break
        else
            echo "MSSQL not ready on attempt $i/$MAX_ATTEMPTS. Retrying in $SLEEP_INTERVAL seconds..."
            sleep $SLEEP_INTERVAL
        fi
    else
        echo "MSSQL container not running on attempt $i/$MAX_ATTEMPTS. Retrying in $SLEEP_INTERVAL seconds..."
        sleep $SLEEP_INTERVAL
    fi
    if [ $i -eq $MAX_ATTEMPTS ]; then
        echo "Error: MSSQL container ${INSTANCE_NAME}_mssql failed to become ready after $MAX_ATTEMPTS attempts."
        exit 1
    fi
done

# Check vault_init completion
echo "Checking vault_init container ${INSTANCE_NAME}_vault_init-1..."
for ((i=1; i<=MAX_ATTEMPTS; i++)); do
    status=$(docker inspect "${INSTANCE_NAME}_vault_init-1" --format '{{.State.Status}}' 2>/dev/null)
    exit_code=$(docker inspect "${INSTANCE_NAME}_vault_init-1" --format '{{.State.ExitCode}}' 2>/dev/null)
    if [ "$status" = "exited" ] && [ "$exit_code" = "0" ]; then
        echo "vault_init completed successfully."
        break
    else
        echo "vault_init is in state $status with exit code $exit_code on attempt $i/$MAX_ATTEMPTS. Retrying in $SLEEP_INTERVAL seconds..."
        sleep $SLEEP_INTERVAL
    fi
    if [ $i -eq $MAX_ATTEMPTS ]; then
        echo "Error: vault_init container ${INSTANCE_NAME}_vault_init-1 failed to complete after $MAX_ATTEMPTS attempts."
        exit 1
    fi
done

# Optionally check Vault service
echo "Checking Vault container ${INSTANCE_NAME}_vault..."
for ((i=1; i<=MAX_ATTEMPTS; i++)); do
    if docker ps -q -f name="${INSTANCE_NAME}_vault" | grep -q .; then
        if docker exec "${INSTANCE_NAME}_vault" vault status > /dev/null 2>&1; then
            echo "Vault is ready."
            break
        else
            echo "Vault not ready on attempt $i/$MAX_ATTEMPTS. Retrying in $SLEEP_INTERVAL seconds..."
            sleep $SLEEP_INTERVAL
        fi
    else
        echo "Vault container not running on attempt $i/$MAX_ATTEMPTS. Retrying in $SLEEP_INTERVAL seconds..."
        sleep $SLEEP_INTERVAL
    fi
    if [ $i -eq $MAX_ATTEMPTS ]; then
        echo "Error: Vault container ${INSTANCE_NAME}_vault failed to become ready after $MAX_ATTEMPTS attempts."
        exit 1
    fi
done

echo "All services are ready."
exit 0