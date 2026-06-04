import io

from .imports import *
from .utils import _create_payload, _handle_api_call, login_view, login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
import docker
import subprocess
import os
from ..DeployService import HEAppEDeployService, HEAppEConfig

import socket

from ..models import InstanceCredentials


def get_port_with_fallback(start_port=8080, max_tries=100):
    """
    Zkusí port start_port. Pokud je obsazený, zkusí start_port + 1 atd.
    """
    for port in range(start_port, start_port + max_tries):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            print(f"Checking port {port}...")
            s.bind(('', port))
            print(f"Port {port} is free.")
            return port, s
        except OSError:
            print(f"Port {port} is in use, trying next port...")
            s.close()
            continue

    raise OSError(f"Nepodařilo se najít volný port v rozsahu {start_port}-{start_port + max_tries}")

import subprocess

def execute_docker_compose_detached(command, compose_dir, timeout=600):
    """Run docker compose safely from Gunicorn without being killed on worker reload."""
    try:
        proc = subprocess.Popen(
            command,
            cwd=compose_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True  # <-- detaches from Gunicorn
        )
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(
            args=command,
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout=stdout,
            stderr=f"Command timed out after {timeout}s.\n{stderr}"
        )
    except Exception as e:
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout="",
            stderr=str(e)
        )


def execute_docker_compose(command, compose_dir, timeout=300):
    """Execute a Docker Compose command safely under Gunicorn."""
    try:
        result = subprocess.run(
            command,
            cwd=compose_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False
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
    try:
        image_tags = ', '.join(container.image.tags) if container.image.tags else 'N/A'
    except docker.errors.ImageNotFound:
        image_tags = 'N/A'
    return {
        'id': container.id,
        'short_id': container.short_id,
        'name': container.name,
        'status': container.status,
        'image': image_tags,
        'service': container.labels.get('com.docker.compose.service', 'N/A'),
        'ports': ports_info,
        'created': container.attrs['Created'][:19] if 'Created' in container.attrs else 'N/A',
        'started_at': container.attrs['State']['StartedAt'][:19] if container.attrs['State']['StartedAt'] else 'N/A'
    }

import random


def generate_secure_password(length=16):
    if length < 8:
        raise ValueError("Password length should be at least 8 characters.")

    lower = string.ascii_lowercase
    upper = string.ascii_uppercase
    digits = string.digits
    all_chars = lower + upper + digits

    # zajistí alespoň jednu malou, jednu velkou a jednu číslici
    password = [
        random.choice(lower),
        random.choice(upper),
        random.choice(digits)
    ]

    # doplní zbytek hesla náhodnými znaky
    password += [random.choice(all_chars) for _ in range(length - 3)]
    random.shuffle(password)
    return ''.join(password)


def wait_for_container_running(container_name, timeout=60, interval=5):
    """Wait until a Docker container is in 'running' state using Docker SDK."""
    client = docker.from_env()
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            container = client.containers.get(container_name)
            container.reload()  # Refresh status
            status = container.status
            print(f"Container {container_name} status: {status}")
            if status == "running":
                print(f"Container {container_name} is running.")
                return True
        except docker.errors.NotFound:
            print(f"Container {container_name} not found yet.")
        time.sleep(interval)

    raise TimeoutError(f"Container {container_name} did not reach 'running' state in {timeout} seconds.")


import secrets
import string


def handle_deployment_action(config, instance_name, ports, s1, s2, s3, s4):
    """Handle the deployment process and return the result."""
    service = HEAppEDeployService(config)
    compose_dir = os.path.join(config.base_path, instance_name, "heappe-core")

    try:

        for s in [s1, s2, s3, s4]:
            if 's' in locals(): s.close()

        admin_password = generate_secure_password()
        vault_password = generate_secure_password()
        sa_password = generate_secure_password()
        data_staging_token = generate_secure_password()

        instance_settings = service.deploy_init(
            instance_name=instance_name,
            username="admin",
            password=admin_password,
            vault_password=vault_password,
            sa_password=sa_password,
            data_staging_token=data_staging_token,
            ports=ports,
            overwrite_existing=True,
            deployed_ip='localhost',
            version=config.repo_branch
        )['instance_settings']

        build_command = [
            "docker", "compose",
            "--profile", "db",
            "--profile", "initVault",
            "--profile", "staging",
            "-p", instance_name,
            "build",  "--no-cache"
        ]
        build_result = execute_docker_compose(build_command, compose_dir)
        print(f"Docker Compose build result done")
        up_command = [
            "docker", "compose",
            "--profile", "db",
            "--profile", "initVault",
            "--profile", "staging",
            "-p", instance_name,
            "up", "-d"
        ]
        up_result = execute_docker_compose(up_command, compose_dir)
        print(f"Docker Compose up done: {up_result.returncode} {up_result.stdout} {up_result.stderr}")
        #wait_for_container_running(f"{instance_name}_mssql", timeout=300, interval=10)
        # Initialize the database with retries

        run_with_retries(instance_name, ports, sa_password)

        restart_command = [
            "docker", "compose",
            "--profile", "db",
            "--profile", "initVault",
            "-p", instance_name,
            "restart"
        ]

        wait_for_container_running(f"{instance_name}_heappe", timeout=300, interval=10)
        wait_for_container_running(f"{instance_name}_mssql", timeout=300, interval=10)

        restart_result = execute_docker_compose(restart_command, compose_dir)
        print(f"Docker Compose restart done: {restart_result.returncode} {restart_result.stdout} {restart_result.stderr}")
        if restart_result.returncode != 0:
            return restart_result, f"Failed to restart containers: {restart_result.stderr}", 'danger'

        #set the instance as deployed in the database
        from ..models import InstanceCredentials
        instance_settings.is_deployed = True
        instance_settings.save()
        return restart_result, "Deployment completed successfully.", 'success'
    except Exception as e:
        print(f"Deployment error: {str(e)}")
        return None, f"Deployment error: {str(e)}", 'danger'

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
        return f"Error performing {action} on container {container_id}: {(e)}", 'danger'

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
        "--profile", "staging",
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

def _set_updating_status(instance_name: str, status: bool):
    try:
        from ..models import InstanceCredentials
        instance_service = InstanceCredentials.objects.filter(instance_name=instance_name).first()
        if instance_service:
            instance_service.is_updating = status
            instance_service.save()
    except Exception as e:
        print(f"Error setting updating status for {instance_name}: {e}")


def handle_update_action(config, instance_name):
    """Handle the update process and return the result."""
    from datetime import datetime
    service = HEAppEDeployService(config)
    compose_dir = os.path.join(config.base_path, instance_name, "heappe-core")
    log_dir = os.path.join(config.base_path, instance_name, "app", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, "update.log")

    def log_message(msg):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{timestamp}] {msg}\n"
        print(msg)
        try:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(formatted)
        except Exception as e:
            print(f"Error writing to update log: {e}")

    try:
        # Clear previous log
        try:
            with open(log_file_path, "w", encoding="utf-8") as f:
                f.write("")
        except Exception:
            pass

        log_message("Starting HEAppE update process...")
        log_message(f"Repository branch/tag: {config.repo_branch}")
        _set_updating_status(instance_name, True)
        log_message("Database status set to updating.")

        # git pull
        git_command = ["git", "pull", "origin", config.repo_branch]
        log_message(f"Running command: {' '.join(git_command)}")
        git_result = subprocess.run(
            git_command,
            cwd=compose_dir,
            capture_output=True,
            text=True,
            check=False
        )
        log_message(f"Git pull finished with return code {git_result.returncode}")
        if git_result.stdout:
            log_message(f"Git stdout:\n{git_result.stdout}")
        if git_result.stderr:
            log_message(f"Git stderr:\n{git_result.stderr}")

        if git_result.returncode != 0:
            log_message("ERROR: Failed to pull latest code. Aborting update.")
            _set_updating_status(instance_name, False)
            return git_result, f"Failed to pull latest code: {git_result.stderr}", 'danger'

        log_message("Updating configuration files (.env and appsettings)...")
        service.update_init(instance_name=instance_name, version=config.repo_branch)
        log_message("Configuration update completed.")

        # rebuild and restart containers
        build_command = [
            "docker", "compose",
            "--profile", "db",
            "--profile", "heappe",
            "--profile", "initVault",
            "--profile", "vault",
            "--profile", "vaultagent",
            "--profile", "sshagent",
            "--profile", "staging",
            "-p", instance_name,
            "build"
        ]
        log_message("Rebuilding Docker containers. This might take a few minutes...")
        build_result = execute_docker_compose(build_command, compose_dir)
        log_message(f"Docker Compose build finished with return code {build_result.returncode}")
        if build_result.stdout:
            log_message(f"Docker Compose build stdout:\n{build_result.stdout}")
        if build_result.stderr:
            log_message(f"Docker Compose build stderr:\n{build_result.stderr}")

        if build_result.returncode != 0:
            log_message("ERROR: Docker Compose build failed. Aborting update.")
            _set_updating_status(instance_name, False)
            return build_result, f"Failed to rebuild containers: {build_result.stderr}", 'danger'

        log_message("Restarting containers with the new build...")
        restart_command = [
            "docker", "compose",
            "--profile", "db",
            "--profile", "heappe",
            "--profile", "initVault",
            "--profile", "vault",
            "--profile", "vaultagent",
            "--profile", "sshagent",
            "--profile", "staging",
            "-p", instance_name,
            "up", "-d"
        ]
        restart_result = execute_docker_compose(restart_command, compose_dir)
        log_message(f"Docker Compose up finished with return code {restart_result.returncode}")
        if restart_result.stdout:
            log_message(f"Docker Compose up stdout:\n{restart_result.stdout}")
        if restart_result.stderr:
            log_message(f"Docker Compose up stderr:\n{restart_result.stderr}")

        if restart_result.returncode != 0:
            log_message("ERROR: Failed to restart containers. Update failed.")
            _set_updating_status(instance_name, False)
            return restart_result, f"Failed to restart containers: {restart_result.stderr}", 'danger'

        log_message("SUCCESS: Update completed successfully.")
        _set_updating_status(instance_name, False)
        return restart_result, "Update completed successfully.", 'success'
    except Exception as e:
        log_message(f"EXCEPTION: Update error: {str(e)}")
        _set_updating_status(instance_name, False)
        return None, f"Update error: {str(e)}", 'danger'


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

import pyodbc
import time

import pymssql
import time

import pymssql

import pymssql

import pymssql

import pymssql

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
                        UserId INT NULL,
                        UserName NVARCHAR(30) NULL,
                        UserEmail NVARCHAR(50) NULL,
                        JobId INT NULL,
                        Message NVARCHAR(1000) NOT NULL,
                        Exception NVARCHAR(MAX),
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

# Retry logic
def run_with_retries(instance_name, ports, password):
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
            db_password=password
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
        #raise Exception("Failed to initialize database after maximum retries.")


import subprocess


def get_remote_tags(repo_url: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", repo_url],
            capture_output=True, text=True, check=True
        )

        tags = [
            line.split("refs/tags/")[1]
            for line in result.stdout.splitlines()
            if "refs/tags/" in line and not line.endswith("^{}")
        ]

        tags = [t for t in tags if t.lower() >= "v6.0.0"]

        tags.sort(key=lambda t: [int(n) for n in t.lower().lstrip('v').split('.') if n.isdigit()], reverse=True)

        return tags

    except subprocess.CalledProcessError:
        return []



import threading

def deploy_background(config, instance_name, ports, s1, s2, s3, s4):
    thread = threading.Thread(
        target=handle_deployment_action,
        args=(config, instance_name, ports, s1, s2, s3, s4),
        daemon=True
    )
    thread.start()

def update_background(config, instance_name):
    thread = threading.Thread(
        target=handle_update_action,
        args=(config, instance_name),
        daemon=True
    )
    thread.start()

from django.utils import timezone
@login_required
@login_required
def deploy_view(request, instance_name: str = '') -> HttpResponse:
    base_path = "/opt/heappe-deployment/"
    repo_url = "https://github.com/It4innovations/HEAppE"
    repo_branch = "V6.0.0"
    version = "v6.0.0"
    ip = "localhost"
    branches = get_remote_tags(repo_url)

    ports = {}
    action_message = None
    action_status = None
    containers = []
    instance_service = None

    # Try to fetch existing instance details if name provided
    if instance_name:
        try:
            instance_service = InstanceCredentials.objects.get(instance_name=instance_name)
        except InstanceCredentials.DoesNotExist:
            instance_service = None

    deployed_version = ""
    latest_version = branches[0].lstrip("vV") if branches else ""
    update_available = False

    if instance_name:
        # 1. Try to get deployed version from Health check
        try:
            if instance_service:
                host = instance_service.heappe_host
                port = instance_service.heappe_port
                # Construct host URL
                host_url = f"{host}:{port}"
                if not host_url.startswith('http'):
                    host_url = 'http://' + host_url
                
                config = hp.Configuration()
                config.host = host_url
                config.verify_ssl = True
                
                api_client = hp.ApiClient(config)
                controller = hp.HealthApi(api_client)
                health_info = controller.heappe_health_get()
                if health_info and health_info.version:
                    deployed_version = health_info.version.lstrip("vV")
        except Exception as e:
            print(f"Healthcheck failed for {instance_name}, falling back to appsettings: {e}")

        # 2. Fallback to appsettings.json if health check failed or returned empty
        if not deployed_version:
            appsettings_path = os.path.join(base_path, instance_name, "app", "confs", "appsettings.json")
            if os.path.exists(appsettings_path):
                try:
                    import json
                    with open(appsettings_path, "r", encoding="utf-8") as f:
                        appsettings_data = json.load(f)
                    deployed_version = appsettings_data.get("ApplicationAPISettings", {}).get("DeploymentSettings", {}).get("Version", "").lstrip("vV")
                except Exception as e:
                    print(f"Error reading appsettings.json: {e}")

        if deployed_version and latest_version:
            def clean_ver(v):
                res = [int(n) for n in v.lower().lstrip('v').split('.') if n.isdigit()]
                return res if res else [0]
            try:
                if clean_ver(latest_version) > clean_ver(deployed_version):
                    update_available = True
            except Exception:
                if latest_version.lower().lstrip('v') != deployed_version.lower().lstrip('v'):
                    update_available = True

    try:
        client = docker.from_env()

        if request.method == 'POST':
            action = request.POST.get('action')

            # If deploying new, get name from form, otherwise use URL param
            if action == 'deploy':
                instance_name = request.POST.get('InstanceName', 'heappe-instance')

            # Form params
            input_repo = request.POST.get('Repository', repo_url)
            input_branch = request.POST.get('RepositoryBranch', "master")
            compose_dir = os.path.join(base_path, instance_name, "heappe-core")

            if action == 'deploy':
                # --- PORT ALLOCATION LOGIC ---
                app_port, s2 = get_port_with_fallback(start_port=5000, max_tries=100)
                data_staging_port, s3 = get_port_with_fallback(start_port=5001, max_tries=100)
                mssql_port, s1 = get_port_with_fallback(start_port=6000, max_tries=100)
                local_port, s4 = get_port_with_fallback(start_port=49005, max_tries=100)
                ports = {
                    "mssql_port": mssql_port,
                    "app_port": app_port,
                    "data_staging_port": data_staging_port,
                    "local_port": local_port
                }

                # --- START BACKGROUND DEPLOYMENT ---
                config = HEAppEConfig(
                    base_path=base_path,
                    repo_url=input_repo,
                    repo_branch=input_branch,
                    default_version=input_branch,
                    default_ip=ip,
                    default_ports=ports,
                    target_dir="heappe-core"
                )

                deploy_background(config, instance_name, ports, s1, s2, s3, s4)

                action_message = "Deployment started in the background."
                action_status = 'info'

                # --- JSON RESPONSE WITH REDIRECT ---

                redirect_url = reverse('deploy_view', kwargs={'instance_name': instance_name})
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'status': 'success',
                        'message': action_message,
                        'instance_name': instance_name,
                        'redirect_url': redirect_url
                    })

            elif action == "update":
                config = HEAppEConfig(
                    base_path=base_path,
                    repo_url=input_repo,
                    repo_branch=input_branch,
                    default_version=input_branch,
                    default_ip=ip,
                    default_ports=ports,
                    target_dir="heappe-core"
                )
                update_background(config, instance_name)
                action_message = "Update started in the background."
                action_status = 'info'

            elif action in ['start', 'stop', 'restart']:
                action_message, action_status = handle_container_action(
                    client, instance_name, action, request.POST.get('container_id')
                )

            elif action in ['start_all', 'restart_all', 'stop_all']:
                action_message, action_status = handle_global_action(compose_dir, instance_name, action)

            # Generic JSON response for non-deploy actions
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                updated_containers = [
                    get_container_details(c) for c in client.containers.list(all=True)
                    if c.labels.get('com.docker.compose.project') == instance_name
                ]
                return JsonResponse({
                    'status': action_status,
                    'message': action_message,
                    'instance_name': instance_name,
                    'containers': updated_containers
                })

        # --- GET REQUEST / PAGE LOAD ---
        # Fetch containers only if we are looking at a specific instance
        if instance_name:
            containers = [
                {'container': c, 'ports': get_container_details(c)['ports']}
                for c in client.containers.list(all=True)
                if c.labels.get('com.docker.compose.project') == instance_name
            ]

    except Exception as e:
        print(f"Error in deploy_view: {e}")
        action_message = "Docker not available or error occurred."
        action_status = 'warning'

    context = {
        "containers": containers,
        "instance_name": instance_name,
        "action_message": action_message,
        "action_status": action_status,
        "repo_url": repo_url,
        "repo_branch": branches[0] if branches else "main",
        "branches": branches,
        "instance_service": instance_service,
        "is_deployed": instance_service.is_deployed if instance_service else False,
        "is_updating": instance_service.is_updating if instance_service else False,
        "deployed_version": deployed_version,
        "latest_version": latest_version,
        "update_available": update_available,
    }
    return render(request, "deploy.html", context)

from django.http import JsonResponse


@login_required
def fetch_repo_branches(request):
    repo_url = request.GET.get('url')
    if not repo_url:
        return JsonResponse({'error': 'No URL provided'}, status=400)

    try:
        branches = get_remote_tags(repo_url)
        return JsonResponse({'branches': branches})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def update_status_view(request, instance_name):
    """Get the current update status and logs for the instance."""
    try:
        from ..models import InstanceCredentials
        instance = InstanceCredentials.objects.filter(instance_name=instance_name).first()
        if not instance:
            return JsonResponse({'status': 'error', 'message': 'Instance not found'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    base_path = "/opt/heappe-deployment/"
    log_file_path = os.path.join(base_path, instance_name, "app", "logs", "update.log")

    logs = ""
    if os.path.exists(log_file_path):
        try:
            with open(log_file_path, "r", encoding="utf-8") as f:
                logs = f.read()
        except Exception as e:
            logs = f"Error reading logs: {e}"

    is_updating = getattr(instance, 'is_updating', False)

    return JsonResponse({
        'status': 'success',
        'is_updating': is_updating,
        'logs': logs
    })

import base64
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import docker

client = docker.from_env()

@login_required
def handle_file_action(request, container_id, action):
    """Handle file operations in container."""
    try:
        container = client.containers.get(container_id)
        if container.labels.get('com.docker.compose.project') != request.POST.get('instance_name'):
            return JsonResponse({'status': 'danger', 'message': 'Unauthorized access.'}, status=403)

        path = request.POST.get('path', '/')
        #if not path.startswith('/app'):
        #    return JsonResponse({'status': 'danger', 'message': 'Access denied to path.'}, status=403)

        if action == 'list':
            exec_result = container.exec_run(f"ls -la {path}")
            files = exec_result.output.decode('utf-8').strip().split('\n')
            return JsonResponse({'status': 'success', 'files': files})

        elif action == 'read':
            exec_result = container.exec_run(f"cat {path}")
            content = exec_result.output.decode('utf-8')
            return JsonResponse({'status': 'success', 'content': content})

        elif action == 'write':
            content = request.POST.get('content', '')
            write_script = f"mkdir -p $(dirname '{path}') && cat > '{path}' <<'EOF'\n{content}\nEOF\n"
            exec_result = container.exec_run(['bash', '-c', write_script])
            return JsonResponse({
                'status': 'success' if exec_result.exit_code == 0 else 'danger',
                'message': exec_result.output.decode('utf-8', errors='ignore')
            })
        elif action == 'delete':
                    exec_result = container.exec_run(f"rm -f {path}")
                    return JsonResponse({'status': 'success' if exec_result.exit_code == 0 else 'danger', 'message': exec_result.output.decode('utf-8')})

        elif action == 'download':
            exec_result = container.exec_run(f"tar -cz {path}")
            if exec_result.exit_code == 0:
                tar_data = base64.b64encode(exec_result.output).decode('utf-8')
                return JsonResponse({'status': 'success', 'data': tar_data, 'filename': os.path.basename(path)})
            return JsonResponse({'status': 'danger', 'message': 'Download failed.'})

        elif action == 'upload':
            file_data = base64.b64decode(request.POST.get('file_data'))
            filename = request.POST.get('filename')
            upload_path = f"{path}/{filename}"
            container.exec_run(f"mkdir -p {path}")
            tar_stream = io.BytesIO(file_data)
            container.put_archive(path=path, data=tar_stream.read())  # Předpokládá tar input pro upload
            return JsonResponse({'status': 'success', 'message': 'Uploaded.'})

    except Exception as e:
        return JsonResponse({'status': 'danger', 'message': str(e)}, status=500)