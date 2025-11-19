import io

from .imports import *
from .utils import _create_payload, _handle_api_call, login_view, login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
import docker
import subprocess
import os
from ..DeployService import HEAppEDeployService, HEAppEConfig


def get_free_port_safe():
    """Helper function to safely allocate a free port (placeholder implementation)."""
    import socket
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    return port, s

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


import secrets
import string


def generate_secure_password(length=12, forbidden_chars=None):
    if length < 8:
        raise ValueError("Password length should be at least 8 characters.")

    if forbidden_chars is None:
        forbidden_chars = set(',^\\\"\'%(){}[]<>:;/?=+*!$&#@|`~')

    alphabet = ''.join(
        c for c in (string.ascii_letters + string.digits)
        if c not in forbidden_chars
    )

    while True:
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in password)
                and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password)):
            return password

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


def generate_secure_password(length=16):
    alphabet = string.ascii_letters + string.digits + string.punctuation
    password = secrets.choice(string.digits)
    password += secrets.choice(string.punctuation)
    password += secrets.choice(string.ascii_uppercase)
    password += secrets.choice(string.ascii_lowercase)
    for _ in range(length - 4):
        password += secrets.choice(alphabet)
    password_list = list(password)
    secrets.SystemRandom().shuffle(password_list)
    return ''.join(password_list)


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

def handle_update_action(config, instance_name):
    """Handle the update process and return the result."""
    service = HEAppEDeployService(config)
    compose_dir = os.path.join(config.base_path, instance_name, "heappe-core")

    try:
        # git pull
        git_command = ["git", "pull", "origin", config.repo_branch]
        git_result = subprocess.run(
            git_command,
            cwd=compose_dir,
            capture_output=True,
            text=True,
            check=False
        )
        print(f"Git pull done: {git_result.returncode} {git_result.stdout} {git_result.stderr}")
        if git_result.returncode != 0:
            return git_result, f"Failed to pull latest code: {git_result.stderr}", 'danger'

        # update appsettings and .env
        service.update_init(instance_name=instance_name, version=config.repo_branch)

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
            "build",  "--no-cache"
        ]


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
        print(f"Docker Compose restart done: {restart_result.returncode} {restart_result.stdout} {restart_result.stderr}")

        if restart_result.returncode != 0:
            return restart_result, f"Failed to restart containers: {restart_result.stderr}", 'danger'

        return restart_result, "Update completed successfully.", 'success'
    except Exception as e:
        print(f"Update error: {str(e)}")
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
        raise Exception("Failed to initialize database after maximum retries.")


def get_remote_tags(repo_url: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", repo_url],
            capture_output=True, text=True, check=True
        )

        tags = []
        for line in result.stdout.splitlines():
            if "refs/tags/" in line:
                tag = line.split("refs/tags/")[1]
                if tag.endswith("^{}"):
                    continue
                if tag >= "V6.0.0":  # filtr od verze 6.0.0
                    tags.append(tag)
        # Sort tags in descending order
        tags.sort(reverse=True)
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
def deploy_view(request, instance_name: str = '') -> HttpResponse:
    base_path = "/opt/heappe-deployment/"
    #repo_url = "https://github.com/It4innovations/HEAppE.git"
    repo_url = "https://github.com/It4innovations/HEAppE"
    repo_branch = "V6.0.0"
    version = "v6.0.0"
    ip = "localhost"
    branches = get_remote_tags(repo_url)

    ports = {}
    action_message = None
    action_status = None
    containers = []

    #get instance from db
    from ..models import InstanceCredentials
    try:
        instance_service = InstanceCredentials.objects.get(instance_name=instance_name)
    except InstanceCredentials.DoesNotExist:
        instance_service = None



    try:
        client = docker.from_env()

        if request.method == 'POST':
            action = request.POST.get('action')
            instance_name = request.POST.get('InstanceName', 'heappe-instance')
            repo_url = request.POST.get('Repository',"https://github.com/It4innovations/HEAppE.git")
            repo_branch = request.POST.get('RepositoryBranch',"master")
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

                deploy_background(HEAppEConfig(base_path=base_path, repo_url=repo_url, repo_branch=repo_branch, default_version=repo_branch, default_ip=ip, default_ports=ports, target_dir="heappe-core"),
                    instance_name, ports, s1, s2, s3, s4
                )
                action_message = "Deployment started in the background. This may take several minutes."
                action_status = 'info'
            elif action == "update":
                update_background(HEAppEConfig(base_path=base_path, repo_url=repo_url, repo_branch=repo_branch, default_version=repo_branch, default_ip=ip, default_ports=ports, target_dir="heappe-core"),
                    instance_name
                )
                action_message = "Update started in the background. This may take several minutes."
                action_status = 'info'




            elif action in ['start', 'stop', 'restart']:
                action_message, action_status = handle_container_action(
                    client, instance_name, action, request.POST.get('container_id')
                )

            elif action in ['start_all', 'restart_all', 'stop_all']:
                action_message, action_status = handle_global_action(compose_dir, instance_name, action)

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                print("AJAX request detected, returning JSON response.")
                updated_containers = [get_container_details(c) for c in client.containers.list(all=True)
                                    if c.labels.get('com.docker.compose.project') == instance_name]
                return JsonResponse({
                    'status': action_status,
                    'message': action_message,
                    'instance_name': instance_name,
                    'deployment_status': {
                        'returncode': None,
                    'deployment_message': {
                        'stdout':  '',
                        'stderr':  ''
                    } if 'result' in locals() else None },
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
        "instance_service": instance_service,
        "is_deployed": instance_service.is_deployed if instance_service else False
    }
    return render(request, "deploy.html", context)


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