from .imports import *
from .utils import _create_payload, _handle_api_call, login_view, login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
import docker
import subprocess
import os
import time
import pymssql
from ..DeployService import HEAppEDeployService, HEAppEConfig

def get_free_port_safe():
    """Helper function to safely allocate a free port."""
    import socket
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    return port, s

def execute_docker_compose(command, compose_dir, timeout=300):
    """Execute a Docker Compose command safely under Gunicorn."""
    try:
        result = subprocess.run(
            command,
            cwd=compose_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True
        )
        return result
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout=e.stdout,
            stderr=f"Command timed out after {timeout} seconds."
        )
    except Exception as e:
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stderr=str(e)
        )

def get_container_details(container):
    """Extract detailed information from a Docker container."""
    port_mappings = container.attrs['NetworkSettings']['Ports']
    ports_info = []
    for container_port, host_ports in port_mappings.items():
        if host_ports:
            for host_port in host_ports:
                ports_info.append(f"{host_port['HostIp']}:{host_port['HostPort']} -> {container_port}")
        else:
            ports_info.append(f"{container_port} (no host mapping)")
    return {
        'id': container.id,
        'short_id': container.short_id,
        'name': container.name,
        'status': container.status,
        'image': ', '.join(container.image.tags) if container.image.tags else 'N/A',
        'service': container.labels.get('com.docker.compose.service', 'N/A'),
        'ports': ports_info,
        'created': container.attrs['Created'][:19] if 'Created' in container.attrs else 'N/A',
        'started_at': container.attrs['State']['StartedAt'][:19] if container.attrs['State']['StartedAt'] else 'N/A'
    }

def generate_secure_password(length=12):
    """Generate a secure password."""
    import secrets
    import string
    if length < 8:
        raise ValueError("Password length should be at least 8 characters.")
    alphabet = string.ascii_letters + string.digits + string.punctuation
    while True:
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in password)
                and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password)
                and any(c in string.punctuation for c in password)):
            return password

def handle_deployment_action(config, instance_name, ports, s1, s2, s3, s4):
    """Handle the deployment process and return the result."""
    service = HEAppEDeployService(config)
    compose_dir = os.path.join(config.base_path, instance_name, "heappe-core")

    try:
        service.deploy_init(
            instance_name=instance_name,
            username="admin",
            password="admin",
            vault_password="Password",
            sa_password="Passw0rd",
            ports=ports,
            overwrite_existing=True,
            deployed_ip='localhost'
        )

        # Define the startup script content
        startup_script_content = """#!/bin/bash

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
"""

        # Create the startup script file
        script_dir = os.path.join("scripts")
        os.makedirs(script_dir, exist_ok=True)  # Create scripts directory if it doesn't exist
        script_path = os.path.join(script_dir, "start_heappe.sh")

        # Write the script to the file
        with open(script_path, "w") as f:
            f.write(startup_script_content)
        print(f"Created startup script at {script_path}")

        # Set executable permissions
        os.chmod(script_path, 0o755)
        print(f"Set executable permissions on {script_path}")

        # Call the startup script
        startup_command = [
            script_path,
            instance_name,
            compose_dir,
            str(ports['mssql_port']),
            "Passw0rd"  # MSSQL SA password
        ]
        startup_result = subprocess.run(
            startup_command,
            capture_output=True,
            text=True,
            timeout=600  # Increased timeout for startup script
        )
        print(f"Startup script result: {startup_result.stdout}, {startup_result.stderr}")

        if startup_result.returncode != 0:
            return subprocess.CompletedProcess(
                args=startup_command,
                returncode=startup_result.returncode,
                stdout=startup_result.stdout,
                stderr=startup_result.stderr
            ), f"Startup script failed: {startup_result.stderr}", 'danger'

        # Initialize the database with retries
        run_with_retries(instance_name, ports)

        # Restart all services to ensure consistency
        restart_command = [
            "docker", "compose",
            "--profile", "db",
            "--profile", "heappe",
            "--profile", "initVault",
            "--profile", "vault",
            "--profile", "vaultagent",
            "--profile", "sshagent",
            "-p", instance_name,
            "restart"
        ]
        restart_result = execute_docker_compose(restart_command, compose_dir)
        return restart_result, "Deployment completed successfully.", 'success' if restart_result.returncode == 0 else 'danger'

    except Exception as e:
        print(f"Deployment error: {str(e)}")
        return None, f"Deployment error: {str(e)}", 'danger'
    finally:
        for s in [s1, s2, s3, s4]:
            if 's' in locals(): s.close()

def handle_container_action(client, instance_name, action, container_id):
    """Handle individual container actions."""
    try:
        container = client.containers.get(container_id)
        if container.labels.get('com.docker.compose.project') != instance_name:
            return f"Container {container_id} does not belong to project {instance_name}.", 'danger'

        if action == 'start':
            container.start()
            return f"Container {container.name} started successfully.", 'success'
        elif action == 'stop':
            container.stop()
            return f"Container {container.name} stopped successfully.", 'success'
        elif action == 'restart':
            container.restart()
            return f"Container {container.name} restarted successfully.", 'success'
    except docker.errors.NotFound:
        return f"Container {container_id} not found.", 'danger'
    except docker.errors.APIError as e:
        return f"Error performing {action} on container {container_id}: {str(e)}", 'danger'

def handle_global_action(compose_dir, instance_name, action):
    """Handle global actions for all containers in the project."""
    command = [
        "docker", "compose",
        "--profile", "db",
        "--profile", "heappe",
        "--profile", "initVault",
        "--profile", "vault",
        "--profile", "vaultagent",
        "--profile", "sshagent",
        "-p", instance_name
    ]
    if action == 'start_all':
        command.extend(["up", "-d"])
        message = "All containers started successfully."
    elif action == 'restart_all':
        command.append("restart")
        message = "All containers restarted successfully."
    elif action == 'stop_all':
        command.append("stop")
        message = "All containers stopped successfully."
    else:
        return f"Invalid action: {action}", 'danger'

    result = execute_docker_compose(command, compose_dir)
    return (
        message if result.returncode == 0 else f"Failed to {action.replace('_all', '')} all containers: {result.stderr}",
        'success' if result.returncode == 0 else 'danger'
    )

def container_logs_view(request, container_id):
    """Fetch logs for a specific container."""
    try:
        client = docker.from_env()
        container = client.containers.get(container_id)
        logs = container.logs(tail=100, timestamps=True).decode('utf-8')
        return JsonResponse({
            'status': 'success',
            'message': 'Logs retrieved successfully.',
            'logs': logs
        })
    except docker.errors.NotFound:
        return JsonResponse({
            'status': 'danger',
            'message': f"Container {container_id} not found."
        }, status=404)
    except docker.errors.APIError as e:
        return JsonResponse({
            'status': 'danger',
            'message': f"Error fetching logs: {str(e)}"
        }, status=500)

def initialize_database(
    server,
    port,
    db_user,
    db_password,
    db_name="heappe-monitoring",
    log_levels=[
        ("Debug", "Debug description"),
        ("Information", "Information description"),
        ("Warning", "Warning description"),
        ("Error", "Error description"),
        ("Critical", "Critical description"),
        ("None", "None description"),
    ]
):
    try:
        # Step 1: Create database if it doesn't exist
        with pymssql.connect(
            server=server,
            port=port,
            user=db_user,
            password=db_password,
            database="master",
            autocommit=True
        ) as conn:
            cursor = conn.cursor()
            cursor.execute(f"IF DB_ID(N'{db_name}') IS NULL CREATE DATABASE [{db_name}]")
            print(f"Database '{db_name}' created or already exists.")

        # Step 2: Connect to the new database for permissions, tables, and inserts
        with pymssql.connect(
            server=server,
            port=port,
            user=db_user,
            password=db_password,
            database=db_name
        ) as conn:
            cursor = conn.cursor()

            # Grant necessary permissions inside the database
            grants = [
                "GRANT CONNECT TO dbo",
                "IF USER_ID('SA') IS NOT NULL GRANT CONNECT TO heappe_management",
                "GRANT VIEW ANY COLUMN ENCRYPTION KEY DEFINITION, VIEW ANY COLUMN MASTER KEY DEFINITION TO [public]"
            ]

            for grant_sql in grants:
                cursor.execute(grant_sql)
            print(f"Permissions granted on database '{db_name}'.")

            # Create LoggingLevelType table
            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'LoggingLevelType')
                BEGIN
                    CREATE TABLE dbo.LoggingLevelType (
                        Id INT IDENTITY PRIMARY KEY,
                        Name NVARCHAR(16) NOT NULL,
                        Description NVARCHAR(255)
                    )
                END
            """)

            # Create Log table
            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Log')
                BEGIN
                    CREATE TABLE dbo.Log (
                        Id BIGINT IDENTITY PRIMARY KEY,
                        IP NVARCHAR(40),
                        InstanceName NVARCHAR(255) NOT NULL,
                        InstanceVersion NVARCHAR(10) NOT NULL,
                        LevelId INT NOT NULL REFERENCES dbo.LoggingLevelType(Id) ON DELETE CASCADE,
                        Date DATETIME2 NOT NULL,
                        Message NVARCHAR(1000) NOT NULL,
                        Exception NVARCHAR(255),
                        Class NVARCHAR(255)
                    );
                    CREATE INDEX IX_Log_LevelId ON dbo.Log(LevelId);
                END
            """)

            # Create __EFMigrationsHistory table
            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = '__EFMigrationsHistory')
                BEGIN
                    CREATE TABLE dbo.__EFMigrationsHistory (
                        MigrationId NVARCHAR(150) PRIMARY KEY,
                        ProductVersion NVARCHAR(32) NOT NULL
                    )
                END
            """)

            # Insert log levels if they don't exist
            for name, desc in log_levels:
                cursor.execute("""
                    IF NOT EXISTS (SELECT 1 FROM dbo.LoggingLevelType WHERE Name = %s)
                    BEGIN
                        INSERT INTO dbo.LoggingLevelType (Name, Description) VALUES (%s, %s)
                    END
                """, (name, name, desc))

            conn.commit()
            print(f"Database '{db_name}' initialized successfully with tables and log levels.")
            return True

    except pymssql.Error as e:
        print(f"Database error: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False

def run_with_retries(instance_name, ports):
    max_attempts = 10
    attempt = 1
    retry_delay = 5  # seconds

    while attempt <= max_attempts:
        print(f"Attempt {attempt} of {max_attempts}")
        success = initialize_database(
            server='localhost',
            port=ports['mssql_port'],
            db_name='heappe-monitoring',
            db_user='SA',
            db_password='Passw0rd'
        )
        if success:
            print("Database initialization succeeded!")
            break
        else:
            print(f"Attempt {attempt} failed. Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)
            attempt += 1

    if attempt > max_attempts:
        print("Max attempts reached. Database initialization failed.")
        raise Exception("Failed to initialize database after maximum retries.")

def get_remote_branches(repo_url: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", repo_url],
            capture_output=True, text=True, check=True
        )
        branches = []
        for line in result.stdout.splitlines():
            if "refs/heads/" in line:
                branches.append(line.split("refs/heads/")[1])
        return branches
    except subprocess.CalledProcessError:
        return []

@login_required(login_url="/login/")
def deploy_view(request, instance_name: str = 'heappe-instance') -> HttpResponse:
    base_path = "/opt/heappe-deployment/"
    repo_url = "https://code.it4i.cz/ADAS-Private/HEAppE/heappe-core.git"
    repo_branch = "develop"
    version = "v6.0.0"
    ip = "localhost"
    branches = get_remote_branches(repo_url)

    ports = {}
    action_message = None
    action_status = None
    containers = []
    try:
        client = docker.from_env()

        if request.method == 'POST':
            action = request.POST.get('action')
            instance_name = request.POST.get('InstanceName', 'heappe-instance')
            repo_url = request.POST.get('Repository', "https://github.com/It4innovations/HEAppE.git")
            repo_branch = request.POST.get('RepositoryBranch', "master")
            compose_dir = os.path.join(base_path, instance_name, "heappe-core")

            if action == 'deploy':
                mssql_port, s1 = get_free_port_safe()
                app_port, s2 = get_free_port_safe()
                data_staging_port, s3 = get_free_port_safe()
                local_port, s4 = get_free_port_safe()
                ports = {
                    "mssql_port": mssql_port,
                    "app_port": app_port,
                    "data_staging_port": data_staging_port,
                    "local_port": local_port
                }
                result, action_message, action_status = handle_deployment_action(
                    HEAppEConfig(base_path=base_path, repo_url=repo_url, repo_branch=repo_branch, default_version=version, default_ip=ip, default_ports=ports, target_dir="heappe-core"),
                    instance_name, ports, s1, s2, s3, s4
                )

            elif action in ['start', 'stop', 'restart']:
                action_message, action_status = handle_container_action(
                    client, instance_name, action, request.POST.get('container_id')
                )

            elif action in ['start_all', 'restart_all', 'stop_all']:
                action_message, action_status = handle_global_action(compose_dir, instance_name, action)

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                updated_containers = [get_container_details(c) for c in client.containers.list(all=True)
                                    if c.labels.get('com.docker.compose.project') == instance_name]
                return JsonResponse({
                    'status': action_status,
                    'message': action_message,
                    'instance_name': instance_name,
                    'deployment_status': {'returncode': result.returncode if result else None} if 'result' in locals() else None,
                    'deployment_message': {
                        'stdout': result.stdout if result and hasattr(result, 'stdout') else '',
                        'stderr': result.stderr if result and hasattr(result, 'stderr') else ''
                    } if 'result' in locals() else None,
                    'ports': ports if action == 'deploy' else {},
                    'containers': updated_containers
                })

        containers = [{'container': c, 'ports': get_container_details(c)['ports']}
                     for c in client.containers.list(all=True)
                     if c.labels.get('com.docker.compose.project') == instance_name]

    except ImportError:
        action_message = "Docker not available, skipping container listing."
        action_status = 'warning'

    context = {
        "containers": containers,
        "deployment_status": locals().get('result'),
        "deployment_message": locals().get('result'),
        "ports": ports,
        "instance_name": instance_name,
        "action_message": action_message,
        "action_status": action_status,
        "repo_url": repo_url,
        "repo_branch": branches[0] if branches else "main",
        "branches": branches,
    }
    return render(request, "deploy.html", context)