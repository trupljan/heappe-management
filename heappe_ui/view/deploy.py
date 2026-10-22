import io
import threading

# Global thread-safe tracking of restarts
RESTART_STATES = {}
RESTART_STATES_LOCK = threading.Lock()

from .imports import *
from .utils import _create_payload, _handle_api_call, login_view, login_required, clean_ver
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse
import docker
import subprocess
import shutil
import os
from ..DeployService import HEAppEDeployService, HEAppEConfig

import socket

from ..models import InstanceCredentials


def get_port_with_fallback(start_port=8080, max_tries=100):
    """
    Tries start_port. If in use, tries start_port + 1, etc.
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

    raise OSError(f"Could not find an available port in range {start_port}-{start_port + max_tries}")

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


def execute_docker_compose(command, compose_dir, timeout=900):
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
    port_mappings = container.attrs.get('NetworkSettings', {}).get('Ports') or {}
    ports_info = []
    mapped = []
    unmapped = []
    for container_port, host_ports in port_mappings.items():
        if host_ports:
            for host_port in host_ports:
                ip = host_port.get('HostIp', '')
                port = host_port.get('HostPort', '')
                if ip in ('0.0.0.0', '::', ''):
                    mapped.append(f"{port}->{container_port}")
                else:
                    mapped.append(f"{ip}:{port}->{container_port}")
        else:
            unmapped.append(f"{container_port}")
    ports_info = mapped + unmapped
    try:
        image_tags = container.attrs.get('Config', {}).get('Image') or 'N/A'
    except Exception:
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

    # ensure at least one lowercase, one uppercase, and one digit
    password = [
        random.choice(lower),
        random.choice(upper),
        random.choice(digits)
    ]

    # fill remaining password length with random characters
    password += [random.choice(all_chars) for _ in range(length - 3)]
    random.shuffle(password)
    return ''.join(password)


def wait_for_container_running(container_name, timeout=60, interval=5):
    """Wait until a Docker container is in 'running' state using Docker SDK."""
    client = docker.from_env()
    start_time = time.time()

    # Determine project name and service name if possible
    # e.g., container_name is like "heappe_heappe" -> project: heappe, service: heappe
    # or "heappe_mssql" -> project: heappe, service: mssql
    project_name = None
    service_name = None
    if "_" in container_name:
        parts = container_name.split("_", 1)
        project_name = parts[0]
        service_name = parts[1]
        # Map "mssql" service name to "db" or check both if compose service is named "db"
        if service_name == "mssql":
            service_name_alt = "db"
        else:
            service_name_alt = None
    else:
        service_name_alt = None

    while time.time() - start_time < timeout:
        container = None
        # 1. Try to get container by exact name
        try:
            container = client.containers.get(container_name)
        except docker.errors.NotFound:
            pass

        # 2. Try with common compose suffixes (e.g. _1, -1, _db_1, -db-1)
        if not container:
            for suffix in ["_1", "-1", "_db_1", "-db-1"]:
                try:
                    container = client.containers.get(f"{container_name}{suffix}")
                    break
                except docker.errors.NotFound:
                    pass

        # 3. Search all containers by project/service labels or name substring
        if not container:
            try:
                for c in client.containers.list(all=True):
                    c_project = c.labels.get('com.docker.compose.project')
                    c_service = c.labels.get('com.docker.compose.service')
                    
                    if project_name and c_project == project_name:
                        if c_service == service_name or (service_name_alt and c_service == service_name_alt):
                            container = c
                            break
                    
                    c_name = c.name.lower()
                    target_lower = container_name.lower()
                    if target_lower in c_name or c_name.replace('-', '_').startswith(target_lower):
                        container = c
                        break
            except Exception as ex:
                print(f"Error listing containers: {ex}")

        if container:
            try:
                container.reload()  # Refresh status
                status = container.status
                print(f"Container {container.name} status: {status}")
                if status == "running":
                    print(f"Container {container.name} is running.")
                    return True
            except Exception as ex:
                print(f"Error checking container status: {ex}")
        else:
            print(f"Container matching {container_name} not found yet.")
            
        time.sleep(interval)

    raise TimeoutError(f"Container matching {container_name} did not reach 'running' state in {timeout} seconds.")


import secrets
import string


def handle_deployment_action(config, instance_name, ports, s1, s2, s3, s4, s5, s6, instance_identifier=None):
    """Handle the deployment process and return the result."""
    from datetime import datetime
    service = HEAppEDeployService(config)
    compose_dir = os.path.join(config.base_path, instance_name, "heappe-core")
    log_dir = os.path.join(config.base_path, instance_name, "app", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, "deploy.log")

    def log_message(msg):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{timestamp}] {msg}\n"
        print(msg)
        try:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(formatted)
        except Exception as e:
            print(f"Error writing to deploy log: {e}")

    try:
        # Clear previous log
        try:
            with open(log_file_path, "w", encoding="utf-8") as f:
                f.write("")
        except Exception:
            pass

        log_message("Starting HEAppE deployment process...")
        log_message(f"Repository URL: {config.repo_url}")
        log_message(f"Repository branch/tag: {config.repo_branch}")
        if instance_identifier:
            log_message(f"HEAppE Identifier: {instance_identifier}")

        for s in [s1, s2, s3, s4, s5, s6]:
            if 's' in locals() and s:
                try:
                    s.close()
                except Exception:
                    pass

        admin_password = generate_secure_password()
        vault_password = generate_secure_password()
        sa_password = generate_secure_password()
        data_staging_token = generate_secure_password()

        log_message("Initializing configuration files and directory structure...")
        clean_ver_str = service.resolve_clean_version(config.repo_branch, instance_name=instance_name)
        init_result = service.deploy_init(
            instance_name=instance_name,
            username="admin",
            password=admin_password,
            vault_password=vault_password,
            sa_password=sa_password,
            data_staging_token=data_staging_token,
            ports=ports,
            overwrite_existing=True,
            deployed_ip='localhost',
            version=clean_ver_str,
            instance_identifier=instance_identifier
        )
        if init_result.get("status") == "error":
            raise RuntimeError(f"deploy_init failed: {init_result.get('message')}")

        instance_settings = init_result['instance_settings']
        log_message("Configuration initialized. Core settings generated.")

        # Re-set updating status to True just in case deploy_init updated it
        _set_updating_status(instance_name, True)

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
        log_message("Building docker containers (this can take a few minutes)...")
        build_result = execute_docker_compose(build_command, compose_dir)
        log_message(f"Docker Compose build finished with return code {build_result.returncode}")
        if build_result.stdout:
            log_message(f"Build stdout:\n{build_result.stdout}")
        if build_result.stderr:
            log_message(f"Build stderr:\n{build_result.stderr}")

        if build_result.returncode != 0:
            raise RuntimeError(f"Docker compose build failed: {build_result.stderr}")

        up_command = [
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
        log_message("Starting containers...")
        up_result = execute_docker_compose(up_command, compose_dir)
        log_message(f"Docker Compose up finished with return code {up_result.returncode}")
        if up_result.stdout:
            log_message(f"Up stdout:\n{up_result.stdout}")
        if up_result.stderr:
            log_message(f"Up stderr:\n{up_result.stderr}")

        if up_result.returncode != 0:
            raise RuntimeError(f"Docker compose up failed: {up_result.stderr}")

        log_message("Running database migrations and initialization...")
        run_with_retries(instance_name, ports, sa_password, logger=log_message)
        log_message("Database initialization completed successfully.")

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
            "restart"
        ]

        log_message("Waiting for heappe and mssql containers to be running...")
        wait_for_container_running(f"{instance_name}_mssql", timeout=900, interval=10)
        wait_for_container_running(f"{instance_name}_heappe", timeout=900, interval=10)

        log_message("Restarting services to apply database and vault configs...")
        restart_result = execute_docker_compose(restart_command, compose_dir)
        log_message(f"Docker Compose restart finished with return code {restart_result.returncode}")
        if restart_result.stdout:
            log_message(f"Restart stdout:\n{restart_result.stdout}")
        if restart_result.stderr:
            log_message(f"Restart stderr:\n{restart_result.stderr}")

        if restart_result.returncode != 0:
            raise RuntimeError(f"Docker compose restart failed: {restart_result.stderr}")

        # Write success log first
        log_message("SUCCESS: Deployment completed successfully.")

        # Set the instance as deployed in the database
        instance_settings.is_deployed = True
        instance_settings.is_updating = False
        instance_settings.save()

        return restart_result, "Deployment completed successfully.", 'success'
    except Exception as e:
        log_message(f"EXCEPTION: Deployment error: {str(e)}")
        _set_updating_status(instance_name, False)
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
        elif action == 'delete':
            container.remove(force=True)
            return f"Container {container.name} deleted successfully.", 'success'
    except docker.errors.NotFound:
        return f"Container {container_id} not found.", 'danger'
    except docker.errors.APIError as e:
        return f"Error performing {action} on container {container_id}: {(e)}", 'danger'

def is_port_open(host, port, timeout=1):
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False

def run_bg_restart_all(compose_dir, instance_name, command, mssql_port, env_path):
    try:
        with RESTART_STATES_LOCK:
            RESTART_STATES[instance_name] = {'status': 'restarting', 'error': None}

        restart_cmd = command + ["restart"]
        restart_result = execute_docker_compose(restart_cmd, compose_dir)
        if restart_result.returncode != 0:
            raise Exception(f"Failed to restart containers: {restart_result.stderr}")

        with RESTART_STATES_LOCK:
            RESTART_STATES[instance_name]['status'] = 'done'

    except Exception as e:
        with RESTART_STATES_LOCK:
            RESTART_STATES[instance_name] = {'status': 'failed', 'error': str(e)}

def handle_global_action(compose_dir, instance_name, action):
    """Handle global actions for all containers in the project."""
    # Read .env to check if telemetry is enabled
    env_path = os.path.join(compose_dir, ".env")
    otel_disabled = True
    mssql_port = None
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line_strip = line.strip()
                    if line_strip.startswith("OTEL_DISABLED="):
                        otel_disabled = (line_strip.split("=", 1)[1].strip().lower() == "true")
                    elif line_strip.startswith("HOST_MSSQL_PORT="):
                        try:
                            mssql_port = int(line_strip.split("=", 1)[1].strip())
                        except ValueError:
                            pass
        except Exception:
            pass

    command = [
        "docker", "compose",
        "--profile", "db",
        "--profile", "heappe",
        "--profile", "initVault",
        "--profile", "vault",
        "--profile", "vaultagent",
        "--profile", "sshagent",
        "--profile", "staging"
    ]
    if not otel_disabled:
        command.extend(["--profile", "telemetry"])

    command.extend(["-p", instance_name])

    if action == 'start_all':
        command.extend(["up", "-d"])
        message = "All containers started successfully."
    elif action == 'restart_all':
        with RESTART_STATES_LOCK:
            state = RESTART_STATES.get(instance_name)
            if state and state.get('status') == 'restarting':
                return "Restart is already in progress.", 'info'

            RESTART_STATES[instance_name] = {'status': 'restarting', 'error': None}

        thread = threading.Thread(
            target=run_bg_restart_all,
            args=(compose_dir, instance_name, command, mssql_port, env_path),
            daemon=True
        )
        thread.start()
        return "Restart initiated in background.", 'info'
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


def teardown_instance(
    instance_name: str,
    base_path: str = "/opt/heappe-deployment/",
    stop_containers: bool = True,
    delete_files: bool = True
) -> dict:
    """
    Shuts down and removes all Docker containers, networks, volumes,
    and optionally deletes deployment files on disk for a given instance.
    """
    results = {
        "containers_stopped": 0,
        "containers_removed": 0,
        "compose_down_success": False,
        "files_removed": False,
        "errors": []
    }

    if not instance_name:
        return results

    # 1. Execute docker compose down if compose directory exists
    if stop_containers:
        candidate_compose_dirs = []
        if base_path:
            candidate_compose_dirs.append(os.path.join(base_path, instance_name, "heappe-core"))
        for bp in ["/opt/heappe-deployment", "/opt/heappe"]:
            p = os.path.join(bp, instance_name, "heappe-core")
            if p not in candidate_compose_dirs:
                candidate_compose_dirs.append(p)

        for compose_dir in candidate_compose_dirs:
            if os.path.isdir(compose_dir):
                try:
                    down_cmd = [
                        "docker", "compose",
                        "--profile", "db",
                        "--profile", "heappe",
                        "--profile", "initVault",
                        "--profile", "vault",
                        "--profile", "vaultagent",
                        "--profile", "sshagent",
                        "--profile", "staging",
                        "--profile", "telemetry",
                        "-p", instance_name,
                        "down", "-v", "--remove-orphans"
                    ]
                    res = execute_docker_compose(down_cmd, compose_dir, timeout=120)
                    if res.returncode == 0:
                        results["compose_down_success"] = True
                        break
                    else:
                        if res.stderr:
                            results["errors"].append(f"Docker compose down note: {res.stderr.strip()}")
                except Exception as e:
                    results["errors"].append(f"Docker compose down error: {e}")

        # 2. Sweep all containers using Docker SDK as a safeguard to ensure no lingering containers exist
        try:
            client = docker.from_env()
            inst_lower = instance_name.lower()
            for c in client.containers.list(all=True):
                labels = getattr(c, 'labels', {}) or {}
                proj = (labels.get('com.docker.compose.project') or '').lower()
                c_name = (getattr(c, 'name', '') or '').lower()

                # Match if container belongs to this project or has instance_name in container name
                is_match = (
                    proj == inst_lower or
                    c_name.startswith(f"{inst_lower}_") or
                    c_name.startswith(f"{inst_lower}-") or
                    c_name.endswith(f"-{inst_lower}") or
                    c_name.endswith(f"_{inst_lower}") or
                    f"_{inst_lower}_" in c_name or
                    f"-{inst_lower}-" in c_name
                )
                if is_match:
                    try:
                        if c.status == 'running':
                            c.stop(timeout=10)
                            results["containers_stopped"] += 1
                    except Exception as e:
                        results["errors"].append(f"Failed to stop container {getattr(c, 'name', 'unknown')}: {e}")
                    try:
                        c.remove(force=True, v=True)
                        results["containers_removed"] += 1
                    except Exception as e:
                        results["errors"].append(f"Failed to remove container {getattr(c, 'name', 'unknown')}: {e}")
        except Exception as e:
            results["errors"].append(f"Docker SDK sweep note: {e}")

    # 3. Safely delete filesystem directories if requested
    if delete_files:
        candidate_paths = []
        if base_path:
            candidate_paths.append((base_path, os.path.join(base_path, instance_name)))
        for bp in ["/opt/heappe-deployment", "/opt/heappe"]:
            p = (bp, os.path.join(bp, instance_name))
            if p not in candidate_paths:
                candidate_paths.append(p)

        for b_root, inst_path in candidate_paths:
            try:
                real_root = os.path.realpath(b_root)
                real_inst = os.path.realpath(inst_path)
                if os.path.commonpath([real_root, real_inst]) == real_root and real_inst != real_root:
                    if os.path.exists(real_inst):
                        shutil.rmtree(real_inst, ignore_errors=True)
                        results["files_removed"] = True
            except Exception as e:
                results["errors"].append(f"Failed to delete directory {inst_path}: {e}")

    # 4. Clear internal memory states
    try:
        with RESTART_STATES_LOCK:
            RESTART_STATES.pop(instance_name, None)
    except Exception:
        pass

    return results


@login_required
def deploy_delete_instance(request, instance_name: str) -> HttpResponse:
    """Delete an instance, stop and remove containers, clean up files and DB."""
    if request.method == 'POST':
        stop_containers = request.POST.get('stop_containers', 'true') in ['true', '1', 'on', True]
        delete_files = request.POST.get('delete_files', 'true') in ['true', '1', 'on', True]

        teardown_result = teardown_instance(
            instance_name=instance_name,
            stop_containers=stop_containers,
            delete_files=delete_files
        )

        # Delete database record if exists
        try:
            from ..models import InstanceCredentials
            InstanceCredentials.objects.filter(instance_name=instance_name).delete()
        except Exception as e:
            print(f"Error deleting instance credentials for {instance_name}: {e}")

        # Clean session
        if request.session.get("chosen_instance") == instance_name:
            request.session.pop("chosen_instance", None)
            request.session.pop("heappe_session_code", None)
            request.session.pop("heappe_host", None)
            request.session.pop("heappe_host_url", None)
            request.session.pop("heappe_use_api_key", None)
            request.session.pop("heappe_last_auth", None)
            request.session.pop("heappe_last_failed_auth", None)

        msg = f"Instance '{instance_name}' has been deleted and shut down successfully."
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'success',
                'message': msg,
                'redirect_url': reverse('instance_credentials_list')
            })

        messages.success(request, msg)
        return redirect('instance_credentials_list')

    return redirect('deploy_view', instance_name=instance_name)


def handle_switch_branch_action(config, instance_name, no_cache=False, update_configs=True):
    """Switch HEAppE git branch/tag, update configs (optional), build and up containers."""
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

        target_ref = (config.repo_branch or "master").strip()
        log_message("Starting HEAppE Switch Branch, Build & Up process...")
        log_message(f"Target instance: {instance_name}")
        log_message(f"Repository URL: {config.repo_url}")
        log_message(f"Target branch / ref: {target_ref}")
        log_message(f"Clean build (--no-cache): {'Yes' if no_cache else 'No'}")
        log_message(f"Update configuration templates: {'Yes' if update_configs else 'No'}")
        _set_updating_status(instance_name, True)
        log_message("Instance status set to updating.")

        # 1. Ensure directory and git repository exist
        if not os.path.exists(os.path.join(compose_dir, ".git")):
            log_message(f"Repository not found at {compose_dir}. Cloning repository...")
            os.makedirs(compose_dir, exist_ok=True)
            clone_cmd = ["git", "clone", "--branch", target_ref, config.repo_url, compose_dir]
            clone_res = subprocess.run(clone_cmd, capture_output=True, text=True, check=False)
            if clone_res.returncode != 0:
                raise RuntimeError(f"Git clone failed: {clone_res.stderr}")
            log_message("Repository cloned successfully.")
        else:
            # 2. Fetch all remote tags and branches
            log_message("Fetching remote branches and tags from origin...")
            fetch_cmd = ["git", "fetch", "origin", "--tags", "--prune"]
            fetch_res = subprocess.run(fetch_cmd, cwd=compose_dir, capture_output=True, text=True, check=False)
            if fetch_res.returncode != 0:
                log_message(f"Git fetch notice: {fetch_res.stderr.strip()}")

            # 3. Preserve .env file
            env_path = os.path.join(compose_dir, ".env")
            env_backup = None
            if os.path.exists(env_path):
                try:
                    with open(env_path, "r", encoding="utf-8") as f:
                        env_backup = f.read()
                except Exception as e:
                    log_message(f"Notice reading .env: {e}")

            # 4. Discard dirty tracked changes so checkout does not fail
            log_message("Cleaning modified tracked files in repository...")
            subprocess.run(["git", "checkout", "--", "."], cwd=compose_dir, capture_output=True, text=True, check=False)

            # 5. Check out target ref
            log_message(f"Switching to target branch/ref: '{target_ref}'...")
            checkout_success = False

            # Check if origin/<target_ref> exists (remote branch)
            chk_remote = subprocess.run(
                ["git", "rev-parse", "--verify", f"origin/{target_ref}"],
                cwd=compose_dir, capture_output=True, text=True, check=False
            )
            if chk_remote.returncode == 0:
                # Checkout or create local tracking branch
                res = subprocess.run(
                    ["git", "checkout", "-B", target_ref, f"origin/{target_ref}"],
                    cwd=compose_dir, capture_output=True, text=True, check=False
                )
                if res.returncode == 0:
                    checkout_success = True
                    log_message(f"Checked out branch '{target_ref}' tracking 'origin/{target_ref}'.")
                    # Pull latest
                    pull_res = subprocess.run(
                        ["git", "pull", "origin", target_ref],
                        cwd=compose_dir, capture_output=True, text=True, check=False
                    )
                    if pull_res.stdout:
                        log_message(f"Git pull output:\n{pull_res.stdout.strip()}")
                else:
                    log_message(f"Warning checking out tracking branch: {res.stderr.strip()}")

            if not checkout_success:
                # Try direct branch/tag checkout
                res = subprocess.run(
                    ["git", "checkout", target_ref],
                    cwd=compose_dir, capture_output=True, text=True, check=False
                )
                if res.returncode == 0:
                    checkout_success = True
                    log_message(f"Checked out '{target_ref}'.")
                else:
                    # Try detached checkout (e.g. tag or commit)
                    res = subprocess.run(
                        ["git", "checkout", "--detach", target_ref],
                        cwd=compose_dir, capture_output=True, text=True, check=False
                    )
                    if res.returncode == 0:
                        checkout_success = True
                        log_message(f"Checked out '{target_ref}' (detached HEAD).")
                    else:
                        raise RuntimeError(f"Git checkout failed for '{target_ref}': {res.stderr}")

            # Restore .env if it was removed
            if env_backup is not None and not os.path.exists(env_path):
                try:
                    with open(env_path, "w", encoding="utf-8") as f:
                        f.write(env_backup)
                    log_message("Restored existing .env configuration file.")
                except Exception as e:
                    log_message(f"Notice restoring .env: {e}")

            # Log current commit hash
            commit_res = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=compose_dir, capture_output=True, text=True, check=False
            )
            cur_commit = commit_res.stdout.strip()
            log_message(f"Active checkout is now at commit: {cur_commit}")

        # 6. Update configuration templates if requested
        if update_configs:
            clean_version = service.resolve_clean_version(target_ref, instance_name=instance_name)
            log_message(f"Updating configuration files (.env and appsettings) for version: {clean_version} (branch: {target_ref})...")
            service.update_init(instance_name=instance_name, version=clean_version)
            log_message("Configuration files successfully updated.")
        else:
            log_message("Preserving existing configuration files (update_configs=False).")

        # 7. Check if telemetry is enabled in .env
        env_path = os.path.join(compose_dir, ".env")
        otel_disabled = True
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("OTEL_DISABLED="):
                            otel_disabled = (line.strip().split("=", 1)[1].strip().lower() == "true")
            except Exception:
                pass

        # 8. Docker compose build
        build_command = [
            "docker", "compose",
            "--profile", "db",
            "--profile", "heappe",
            "--profile", "initVault",
            "--profile", "vault",
            "--profile", "vaultagent",
            "--profile", "sshagent",
            "--profile", "staging"
        ]
        if not otel_disabled:
            build_command.extend(["--profile", "telemetry"])
        build_command.extend(["-p", instance_name, "build"])
        if no_cache:
            build_command.append("--no-cache")

        log_message(f"Building Docker containers ({'clean build --no-cache' if no_cache else 'cached build'})...")
        build_result = execute_docker_compose(build_command, compose_dir)
        log_message(f"Docker Compose build finished with return code {build_result.returncode}")
        if build_result.stdout:
            log_message(f"Build stdout:\n{build_result.stdout}")
        if build_result.stderr:
            log_message(f"Build stderr:\n{build_result.stderr}")

        if build_result.returncode != 0:
            raise RuntimeError(f"Docker Compose build failed: {build_result.stderr}")

        # 9. Docker compose up
        up_command = [
            "docker", "compose",
            "--profile", "db",
            "--profile", "heappe",
            "--profile", "initVault",
            "--profile", "vault",
            "--profile", "vaultagent",
            "--profile", "sshagent",
            "--profile", "staging"
        ]
        if not otel_disabled:
            up_command.extend(["--profile", "telemetry"])
        up_command.extend(["-p", instance_name, "up", "-d"])

        log_message("Starting Docker containers (docker compose up -d)...")
        up_result = execute_docker_compose(up_command, compose_dir)
        log_message(f"Docker Compose up finished with return code {up_result.returncode}")
        if up_result.stdout:
            log_message(f"Up stdout:\n{up_result.stdout}")
        if up_result.stderr:
            log_message(f"Up stderr:\n{up_result.stderr}")

        if up_result.returncode != 0:
            raise RuntimeError(f"Docker Compose up failed: {up_result.stderr}")

        log_message(f"SUCCESS: Branch '{target_ref}' switched, containers built and started successfully.")
        _set_updating_status(instance_name, False)
        return up_result, f"Branch '{target_ref}' checked out, build & up completed successfully.", 'success'
    except Exception as e:
        log_message(f"EXCEPTION: Switch branch & build error: {str(e)}")
        _set_updating_status(instance_name, False)
        return None, f"Switch branch & build error: {str(e)}", 'danger'


def handle_update_action(config, instance_name):
    """Handle standard update process."""
    return handle_switch_branch_action(config, instance_name, no_cache=False, update_configs=True)


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

try:
    import pyodbc
except ImportError:
    pyodbc = None
import time
try:
    import pymssql
except ImportError:
    pymssql = None

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
    ],
    logger=print
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
            logger(f"Database '{db_name}' created or already exists.")

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
            logger(f"Permissions granted on database '{db_name}'.")

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
            logger(f"Database '{db_name}' initialized successfully with tables and log levels.")
            return True

    except pymssql.Error as e:
        logger(f"Database error: {e}")
        return False
    except Exception as e:
        logger(f"Unexpected error: {e}")
        return False

# Retry logic
def run_with_retries(instance_name, ports, password, logger=print):
    max_attempts = 10
    attempt = 1
    retry_delay = 5  # seconds

    while attempt <= max_attempts:
        logger(f"Attempt {attempt} of {max_attempts}")
        success = initialize_database(
            server='localhost',
            port=ports['mssql_port'],
            db_name='heappe-monitoring',
            db_user='SA',
            db_password=password,
            logger=logger
        )
        if success:
            logger("Database initialization succeeded!")
            break
        else:
            logger(f"Attempt {attempt} failed. Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)
            attempt += 1

    if attempt > max_attempts:
        logger("Max attempts reached. Database initialization failed.")


import subprocess


def get_remote_refs(repo_url: str) -> dict:
    """Fetch remote branches and tags separately."""
    try:
        # Fetch tags
        result_tags = subprocess.run(
            ["git", "ls-remote", "--tags", repo_url],
            capture_output=True, text=True, check=True, timeout=5
        )
        tags = []
        for line in result_tags.stdout.splitlines():
            if "refs/tags/" in line and not line.endswith("^{}"):
                parts = line.split("refs/tags/")
                if len(parts) > 1:
                    tags.append(parts[1])

        # Keep version >= v6.0.0, and sort them
        version_tags = [t for t in tags if t.lower() >= "v6.0.0"]
        try:
            version_tags.sort(key=lambda t: [int(n) for n in t.lower().lstrip('v').split('.') if n.isdigit()], reverse=True)
        except Exception:
            version_tags.sort(reverse=True)

        # Fetch branches (heads)
        result_heads = subprocess.run(
            ["git", "ls-remote", "--heads", repo_url],
            capture_output=True, text=True, check=True, timeout=5
        )
        branches = []
        for line in result_heads.stdout.splitlines():
            if "refs/heads/" in line:
                parts = line.split("refs/heads/")
                if len(parts) > 1:
                    branches.append(parts[1])
        branches.sort()

        # Combine: version tags first, then branches, then any other tags
        all_refs = version_tags + branches + [t for t in tags if t not in version_tags]

        # De-duplicate while preserving order
        seen = set()
        unique_refs = []
        for r in all_refs:
            if r not in seen:
                seen.add(r)
                unique_refs.append(r)

        return {
            "branches": branches,
            "tags": version_tags,
            "all": unique_refs
        }

    except Exception:
        return {"branches": [], "tags": [], "all": []}


def get_remote_tags(repo_url: str) -> list[str]:
    """Fetch remote tags and branches as a flat list for compatibility."""
    return get_remote_refs(repo_url).get("all", [])


def get_current_git_ref(compose_dir: str) -> dict:
    """Return the currently checked-out branch, commit hash, and description of the HEAppE repository."""
    if not compose_dir or not os.path.exists(os.path.join(compose_dir, ".git")):
        return {
            "branch": "",
            "commit": "",
            "description": "Not deployed / not a git repository",
            "is_repo": False
        }
    try:
        branch_res = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=compose_dir, capture_output=True, text=True, timeout=5
        )
        branch = branch_res.stdout.strip()

        commit_res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=compose_dir, capture_output=True, text=True, timeout=5
        )
        commit = commit_res.stdout.strip()

        desc_res = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            cwd=compose_dir, capture_output=True, text=True, timeout=5
        )
        desc = desc_res.stdout.strip()

        ref_name = branch or desc or "unknown"
        desc_text = f"{ref_name} ({commit})" if commit else ref_name
        return {
            "branch": ref_name,
            "commit": commit,
            "description": desc_text,
            "is_repo": True
        }
    except Exception as e:
        return {
            "branch": "",
            "commit": "",
            "description": f"Git error: {e}",
            "is_repo": False
        }


import threading

def deploy_background(config, instance_name, ports, s1, s2, s3, s4, s5, s6, instance_identifier=None):
    thread = threading.Thread(
        target=handle_deployment_action,
        args=(config, instance_name, ports, s1, s2, s3, s4, s5, s6),
        kwargs={'instance_identifier': instance_identifier},
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

def switch_branch_background(config, instance_name, no_cache=False, update_configs=True):
    thread = threading.Thread(
        target=handle_switch_branch_action,
        args=(config, instance_name, no_cache, update_configs),
        daemon=True
    )
    thread.start()

def regenerate_configs_background(config, instance_name):
    thread = threading.Thread(
        target=handle_regenerate_configs_action,
        args=(config, instance_name),
        daemon=True
    )
    thread.start()

from django.utils import timezone
@login_required
def deploy_view(request, instance_name: str = '') -> HttpResponse:
    base_path = "/opt/heappe-deployment/"
    repo_url = "https://github.com/It4innovations/HEAppE"
    version = "v6.0.0"
    ip = "localhost"
    remote_refs = get_remote_refs(repo_url)
    branches = remote_refs["all"]
    branch_list = remote_refs["branches"]
    tag_list = remote_refs["tags"]
    repo_branch = branch_list[0] if branch_list else (branches[0] if branches else "master")

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
                instance_name = request.POST.get('InstanceName', 'heappe-instance').strip()
                instance_identifier = request.POST.get('InstanceIdentifier', '').strip() or instance_name

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
                otel_grpc_port, s5 = get_port_with_fallback(start_port=4317, max_tries=100)
                otel_jaeger_port, s6 = get_port_with_fallback(start_port=16686, max_tries=100)
                ports = {
                    "mssql_port": mssql_port,
                    "app_port": app_port,
                    "data_staging_port": data_staging_port,
                    "local_port": local_port,
                    "otel_grpc_port": otel_grpc_port,
                    "otel_jaeger_port": otel_jaeger_port
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

                # Pre-create instance credentials in database to avoid race condition and mark as deploying (is_updating=True)
                service = HEAppEDeployService(config)
                service.save_instance_settings(
                    instance_name=instance_name,
                    heappe_host=ip,
                    heappe_login="admin",
                    heappe_password="",
                    log_db_host=ip,
                    heappe_port=app_port,
                    log_db_port=str(mssql_port),
                    log_db_user="SA",
                    log_db_password="",
                    log_db_database="heappe-monitoring",
                    is_deployed=False
                )
                _set_updating_status(instance_name, True)

                # Set in session as chosen instance
                request.session["chosen_instance"] = instance_name
                request.session["force_reauth"] = True
                # Clear old instance connection variables to prevent leakage/fallback
                request.session.pop("heappe_session_code", None)
                request.session.pop("heappe_host", None)
                request.session.pop("heappe_host_url", None)
                request.session.pop("heappe_use_api_key", None)
                request.session.pop("heappe_last_auth", None)

                deploy_background(config, instance_name, ports, s1, s2, s3, s4, s5, s6, instance_identifier=instance_identifier)

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
                # Fallback for non-AJAX (direct form submit without JS)
                from django.http import HttpResponseRedirect
                return HttpResponseRedirect(redirect_url)

            elif action in ["update", "switch_branch"]:
                clean_build = request.POST.get('clean_build') in ['true', '1', 'on', True]
                update_configs = request.POST.get('update_configs', 'true') in ['true', '1', 'on', True]
                custom_branch = request.POST.get('CustomBranch', '').strip()
                target_branch = custom_branch if custom_branch else input_branch

                config = HEAppEConfig(
                    base_path=base_path,
                    repo_url=input_repo,
                    repo_branch=target_branch,
                    default_version=target_branch,
                    default_ip=ip,
                    default_ports=ports,
                    target_dir="heappe-core"
                )
                # Invalidate middleware update cache to force a recheck on the next request
                request.session.pop("last_middleware_check_time", None)
                request.session.pop("last_middleware_checked_instance", None)
                request.session.pop("middleware_update_available", None)
                request.session.pop("middleware_deployed_version", None)
                request.session.pop("middleware_latest_version", None)

                switch_branch_background(config, instance_name, no_cache=clean_build, update_configs=update_configs)
                action_message = f"Switching to branch '{target_branch}', building and starting containers in background."
                action_status = 'info'

            elif action == "regenerate_configs":
                config = HEAppEConfig(
                    base_path=base_path,
                    repo_url=input_repo,
                    repo_branch=input_branch,
                    default_version=input_branch,
                    default_ip=ip,
                    default_ports=ports,
                    target_dir="heappe-core"
                )
                regenerate_configs_background(config, instance_name)
                action_message = "Configuration regeneration started in the background."
                action_status = 'info'

            elif action in ['start', 'stop', 'restart', 'delete']:
                action_message, action_status = handle_container_action(
                    client, instance_name, action, request.POST.get('container_id')
                )

            elif action == 'status_poll':
                # Lightweight read-only poll: just return current container statuses as JSON
                with RESTART_STATES_LOCK:
                    restart_info = RESTART_STATES.get(instance_name, {'status': 'none', 'error': None})
                if restart_info.get('status') in ['stopping', 'db', 'vault', 'services']:
                    return JsonResponse({
                        'status': 'ok',
                        'instance_name': instance_name,
                        'containers': [],
                        'restart_status': restart_info.get('status'),
                        'restart_error': restart_info.get('error')
                    })
                poll_containers = [
                    get_container_details(c) for c in client.containers.list(all=True)
                    if c.labels.get('com.docker.compose.project') == instance_name
                ]
                with RESTART_STATES_LOCK:
                    restart_info = RESTART_STATES.get(instance_name, {'status': 'none', 'error': None})
                return JsonResponse({
                    'status': 'ok',
                    'instance_name': instance_name,
                    'containers': poll_containers,
                    'restart_status': restart_info.get('status'),
                    'restart_error': restart_info.get('error')
                })

            elif action in ['start_all', 'restart_all', 'stop_all']:
                action_message, action_status = handle_global_action(compose_dir, instance_name, action)

            elif action in ['delete_instance', 'teardown']:
                stop_containers = request.POST.get('stop_containers', 'true') in ['true', '1', 'on', True]
                delete_files = request.POST.get('delete_files', 'true') in ['true', '1', 'on', True]
                teardown_instance(instance_name, base_path=base_path, stop_containers=stop_containers, delete_files=delete_files)
                try:
                    InstanceCredentials.objects.filter(instance_name=instance_name).delete()
                except Exception as e:
                    print(f"Error deleting instance credentials: {e}")

                if request.session.get("chosen_instance") == instance_name:
                    request.session.pop("chosen_instance", None)
                    request.session.pop("heappe_session_code", None)
                    request.session.pop("heappe_host", None)
                    request.session.pop("heappe_host_url", None)
                    request.session.pop("heappe_use_api_key", None)
                    request.session.pop("heappe_last_auth", None)
                    request.session.pop("heappe_last_failed_auth", None)

                messages.success(request, f"Instance '{instance_name}' has been deleted and shut down successfully.")
                redirect_url = reverse('instance_credentials_list')
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'status': 'success',
                        'message': f"Instance '{instance_name}' deleted and shut down.",
                        'redirect_url': redirect_url
                    })
                from django.http import HttpResponseRedirect
                return HttpResponseRedirect(redirect_url)

            # Generic JSON response for non-deploy actions
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                updated_containers = [
                    get_container_details(c) for c in client.containers.list(all=True)
                    if c.labels.get('com.docker.compose.project') == instance_name
                ]
                def get_sort_weight(item):
                    name = item['name'].lower()
                    if 'heappe' in name and 'vault' not in name:
                        return 1
                    elif 'datastaging' in name:
                        return 2
                    elif 'mssql' in name or 'db' in name:
                        return 3
                    elif 'vault' in name:
                        if 'vaultagent' in name:
                            return 5
                        elif 'init' in name:
                            return 6
                        elif 'unseal' in name:
                            return 7
                        return 4
                    elif 'sshagent' in name or 'ssh-agent' in name:
                        return 8
                    return 100
                updated_containers.sort(key=get_sort_weight)
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
            def get_sort_weight(item):
                name = item['container'].name.lower()
                if 'heappe' in name and 'vault' not in name:
                    return 1
                elif 'datastaging' in name:
                    return 2
                elif 'mssql' in name or 'db' in name:
                    return 3
                elif 'vault' in name:
                    if 'vaultagent' in name:
                        return 5
                    elif 'init' in name:
                        return 6
                    elif 'unseal' in name:
                        return 7
                    return 4
                elif 'sshagent' in name or 'ssh-agent' in name:
                    return 8
                return 100
            containers.sort(key=get_sort_weight)

    except Exception as e:
        print(f"Error in deploy_view: {e}")
        action_message = "Docker not available or error occurred."
        action_status = 'warning'

    with RESTART_STATES_LOCK:
        restart_info = RESTART_STATES.get(instance_name, {'status': 'none', 'error': None})

    compose_dir = os.path.join(base_path, instance_name, "heappe-core") if instance_name else ""
    current_git_ref = get_current_git_ref(compose_dir) if compose_dir else {"branch": "", "commit": "", "description": "", "is_repo": False}

    is_deployed = instance_service.is_deployed if instance_service else False
    is_updating = instance_service.is_updating if instance_service else False

    deployment_failed = False
    deployment_error = ""
    deploy_logs = ""

    if instance_name and not is_deployed and not is_updating:
        log_dir = os.path.join(base_path, instance_name, "app", "logs")
        deploy_log = os.path.join(log_dir, "deploy.log")
        if os.path.exists(deploy_log):
            try:
                with open(deploy_log, "r", encoding="utf-8") as f:
                    deploy_logs = f.read()

                has_success = ("SUCCESS:" in deploy_logs or "Deployment completed successfully" in deploy_logs)
                if not has_success and deploy_logs.strip():
                    deployment_failed = True
                    for line in reversed(deploy_logs.splitlines()):
                        line_s = line.strip()
                        if "EXCEPTION:" in line_s or "Deployment error:" in line_s or "Error" in line_s or "failed" in line_s.lower():
                            deployment_error = line_s
                            break
                    if not deployment_error:
                        deployment_error = "Deployment process terminated unexpectedly. Review logs for details."
            except Exception as e:
                print(f"Error inspecting deploy.log: {e}")

    context = {
        "containers": containers,
        "instance_name": instance_name,
        "action_message": action_message,
        "action_status": action_status,
        "repo_url": repo_url,
        "repo_branch": current_git_ref.get("branch") or (branch_list[0] if branch_list else (branches[0] if branches else "master")),
        "branches": branches,
        "branch_list": branch_list,
        "tag_list": tag_list,
        "current_git_ref": current_git_ref,
        "instance_service": instance_service,
        "is_deployed": is_deployed,
        "is_updating": is_updating,
        "deployment_failed": deployment_failed,
        "deployment_error": deployment_error,
        "deploy_logs": deploy_logs,
        "deployed_version": deployed_version,
        "latest_version": latest_version,
        "update_available": update_available,
        "restart_status": restart_info.get('status'),
    }
    return render(request, "deploy.html", context)

from django.http import JsonResponse


@login_required
def fetch_repo_branches(request):
    repo_url = request.GET.get('url')
    if not repo_url:
        return JsonResponse({'error': 'No URL provided'}, status=400)

    try:
        refs = get_remote_refs(repo_url)
        return JsonResponse({
            'branches': refs.get("all", []),
            'branch_list': refs.get("branches", []),
            'tag_list': refs.get("tags", [])
        })
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
    log_dir = os.path.join(base_path, instance_name, "app", "logs")
    deploy_log = os.path.join(log_dir, "deploy.log")
    update_log = os.path.join(log_dir, "update.log")

    # Always pick the most recently modified log file so we never read the wrong
    # file when is_deployed flips mid-deployment (the old is_deployed-based logic
    # would switch to update.log while the background thread was still writing to
    # deploy.log, resulting in empty logs and a false "Deployment Failed" state).
    log_file_path = None
    best_mtime = -1.0
    for candidate in [deploy_log, update_log]:
        if os.path.exists(candidate):
            try:
                mtime = os.path.getmtime(candidate)
                if mtime > best_mtime:
                    best_mtime = mtime
                    log_file_path = candidate
            except Exception:
                pass

    logs = ""
    if log_file_path and os.path.exists(log_file_path):
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

def get_docker_client():
    try:
        return docker.from_env()
    except Exception:
        return None

@login_required
def handle_file_action(request, container_id, action):
    """Handle file operations in container."""
    try:
        client = get_docker_client()
        if not client:
            return JsonResponse({'status': 'danger', 'message': 'Docker environment not accessible.'}, status=500)
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
            container.exec_run(f"mkdir -p {path}")
            # put_archive expects a tar stream, so we build one in memory
            import tarfile
            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode='w') as tar:
                file_info = tarfile.TarInfo(name=filename)
                file_info.size = len(file_data)
                tar.addfile(file_info, io.BytesIO(file_data))
            tar_buffer.seek(0)
            container.put_archive(path=path, data=tar_buffer)
            return JsonResponse({'status': 'success', 'message': 'Uploaded.'})

    except Exception as e:
        return JsonResponse({'status': 'danger', 'message': str(e)}, status=500)


@login_required
def instance_config_view(request, instance_name):
    """Graphical tree editor and manager for appsettings.json or appsettings-data.json of the HEAppE instance."""
    from ..models import InstanceCredentials
    try:
        instance_service = InstanceCredentials.objects.get(instance_name=instance_name)
    except InstanceCredentials.DoesNotExist:
        return HttpResponse("Instance not found.", status=404)

    # Determine which configuration file is selected
    selected_file = request.GET.get('file', 'appsettings.json')
    if selected_file not in ['appsettings.json', 'appsettings-data.json']:
        selected_file = 'appsettings.json'

    client = docker.from_env()
    target_container = None
    try:
        # 1. Try to find the exact container associated with the selected file type
        for c in client.containers.list(all=True):
            if c.labels.get('com.docker.compose.project') == instance_name:
                service_name = c.labels.get('com.docker.compose.service', '')
                if selected_file == 'appsettings-data.json':
                    if 'datastaging' in service_name or 'datastaging' in c.name:
                        target_container = c
                        break
                else:
                    if 'heappe' in service_name or 'heappe' in c.name:
                        target_container = c
                        break
        # 2. Fallback to any of the core containers if target is not found (since they mount the same volume)
        if not target_container:
            for c in client.containers.list(all=True):
                if c.labels.get('com.docker.compose.project') == instance_name:
                    service_name = c.labels.get('com.docker.compose.service', '')
                    if 'heappe' in service_name or 'heappe' in c.name or 'datastaging' in service_name or 'datastaging' in c.name:
                        target_container = c
                        break
    except Exception as e:
        return render(request, "instance_config.html", {
            "instance_name": instance_name,
            "error_message": f"Could not list Docker containers: {e}",
            "instance_service": instance_service,
            "selected_file": selected_file,
        })

    if not target_container:
        return render(request, "instance_config.html", {
            "instance_name": instance_name,
            "error_message": "Associated container (heappe/datastaging) not found or not created yet.",
            "instance_service": instance_service,
            "selected_file": selected_file,
        })

    config_path = f"/opt/heappe/confs/{selected_file}"

    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'save':
            content = request.POST.get('content', '')
            write_script = f"mkdir -p $(dirname '{config_path}') && cat > '{config_path}' <<'EOF'\n{content}\nEOF\n"
            exec_result = target_container.exec_run(['bash', '-c', write_script])
            if exec_result.exit_code == 0:
                return JsonResponse({'status': 'success', 'message': 'Configuration saved successfully.'})
            else:
                return JsonResponse({
                    'status': 'danger', 
                    'message': f"Failed to write configuration: {exec_result.output.decode('utf-8', errors='ignore')}"
                }, status=500)
                
        elif action == 'restart':
            base_path = "/opt/heappe-deployment/"
            compose_dir = os.path.join(base_path, instance_name, "heappe-core")
            # Trigger global restart
            action_message, action_status = handle_global_action(compose_dir, instance_name, 'restart_all')
            return JsonResponse({'status': action_status, 'message': action_message})

        elif action == 'status_poll':
            # Lightweight read-only poll: just return current container statuses as JSON
            with RESTART_STATES_LOCK:
                restart_info = RESTART_STATES.get(instance_name, {'status': 'none', 'error': None})
            if restart_info.get('status') in ['stopping', 'db', 'vault', 'services']:
                return JsonResponse({
                    'status': 'ok',
                    'instance_name': instance_name,
                    'containers': [],
                    'restart_status': restart_info.get('status'),
                    'restart_error': restart_info.get('error')
                })
            poll_containers = [
                get_container_details(c) for c in client.containers.list(all=True)
                if c.labels.get('com.docker.compose.project') == instance_name
            ]
            with RESTART_STATES_LOCK:
                restart_info = RESTART_STATES.get(instance_name, {'status': 'none', 'error': None})
            return JsonResponse({
                'status': 'ok',
                'instance_name': instance_name,
                'containers': poll_containers,
                'restart_status': restart_info.get('status'),
                'restart_error': restart_info.get('error')
            })

        elif action == 'test_oidc':
            authority = (request.POST.get('authority') or '').strip()
            if not authority:
                return JsonResponse({'status': 'danger', 'message': 'Authority URL cannot be empty.'}, status=400)

            well_known_url = authority.rstrip('/')
            if not well_known_url.endswith('.well-known/openid-configuration'):
                well_known_url += '/.well-known/openid-configuration'

            import urllib.request
            import urllib.error
            import json as json_lib
            import ssl

            try:
                allow_insecure = request.POST.get('allow_insecure', 'false').lower() == 'true'
                ctx = ssl.create_default_context()
                if allow_insecure:
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE

                req = urllib.request.Request(
                    well_known_url,
                    headers={'User-Agent': 'HEAppE-Management-Admin', 'Accept': 'application/json'}
                )
                with urllib.request.urlopen(req, timeout=6, context=ctx) as response:
                    if response.status == 200:
                        payload = json_lib.loads(response.read().decode('utf-8'))
                        return JsonResponse({
                            'status': 'success',
                            'message': 'Successfully connected to OIDC discovery endpoint.',
                            'details': {
                                'issuer': payload.get('issuer', ''),
                                'authorization_endpoint': payload.get('authorization_endpoint', ''),
                                'token_endpoint': payload.get('token_endpoint', ''),
                                'userinfo_endpoint': payload.get('userinfo_endpoint', ''),
                                'introspection_endpoint': payload.get('introspection_endpoint', ''),
                                'jwks_uri': payload.get('jwks_uri', ''),
                            }
                        })
                    else:
                        return JsonResponse({'status': 'danger', 'message': f'Server returned HTTP {response.status}'}, status=400)
            except urllib.error.HTTPError as e:
                return JsonResponse({'status': 'danger', 'message': f'HTTP Error {e.code}: {e.reason}'}, status=400)
            except urllib.error.URLError as e:
                return JsonResponse({'status': 'danger', 'message': f'Connection failed: {str(e.reason)}'}, status=400)
            except Exception as e:
                return JsonResponse({'status': 'danger', 'message': f'Error: {str(e)}'}, status=400)

    # GET request - read config content
    try:
        exec_result = target_container.exec_run(f"cat {config_path}")
        if exec_result.exit_code == 0:
            config_content = exec_result.output.decode('utf-8')
        else:
            config_content = "{}" # Fallback
    except Exception as e:
        config_content = "{}"

    with RESTART_STATES_LOCK:
        restart_info = RESTART_STATES.get(instance_name, {'status': 'none', 'error': None})

    context = {
        "instance_name": instance_name,
        "config_content": config_content,
        "instance_service": instance_service,
        "container_id": target_container.id,
        "selected_file": selected_file,
        "restart_status": restart_info.get('status'),
    }
    return render(request, "instance_config.html", context)


@login_required
def toggle_telemetry_view(request, instance_name):
    """View to enable/disable OpenTelemetry for a given HEAppE instance."""
    if request.method != "POST":
        return JsonResponse({'status': 'danger', 'message': 'Only POST method is allowed.'}, status=405)

    action = request.POST.get('action') # 'enable' or 'disable'
    base_path = "/opt/heappe-deployment/"
    env_path = os.path.join(base_path, instance_name, "heappe-core", ".env")
    compose_dir = os.path.join(base_path, instance_name, "heappe-core")

    if not os.path.exists(env_path):
        return JsonResponse({'status': 'danger', 'message': f'Config directory or .env not found for instance: {instance_name}'}, status=404)

    # Read env variables
    env_lines = []
    env_vars = {}
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                env_lines.append(line)
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, v = stripped.split("=", 1)
                    env_vars[k.strip()] = v.strip()
    except Exception as e:
        return JsonResponse({'status': 'danger', 'message': f'Failed to read .env file: {str(e)}'}, status=500)

    # Check that OTEL keys are present in .env – older configs may not have them.
    # In that case, instruct the user to regenerate configs first.
    missing_otel_keys = [k for k in ('OTEL_DISABLED', 'OTEL_HOST_GRPC_PORT', 'OTEL_JAEGER_CLIENT_PORT') if k not in env_vars]
    if missing_otel_keys:
        return JsonResponse({
            'status': 'warning',
            'message': (
                'OpenTelemetry configuration keys are missing from the instance .env file '
                f'({", ".join(missing_otel_keys)}). '
                'This usually means the instance was deployed before OTEL support was added. '
                'Please go to the <strong>Maintenance</strong> tab and click '
                '<strong>Regenerate &amp; Restart</strong> to update the configuration, then try again.'
            ),
            'needs_regen': True
        }, status=409)

    if action == 'enable':
        # 1. Verify ports – only reallocate if OTEL is currently disabled.
        # If OTEL is already enabled the running containers already hold those
        # ports, so we must keep the existing values to avoid overwriting the
        # .env with a different port and breaking the running stack.
        otel_currently_disabled = (env_vars.get('OTEL_DISABLED', 'true').lower() == 'true')

        otel_grpc = int(env_vars.get('OTEL_HOST_GRPC_PORT', 4317))
        otel_jaeger = int(env_vars.get('OTEL_JAEGER_CLIENT_PORT', 16686))

        if otel_currently_disabled:
            # Only reallocate ports when OTEL was disabled (containers not running).
            grpc_free, s_grpc = get_port_with_fallback(start_port=otel_grpc, max_tries=100)
            jaeger_free, s_jaeger = get_port_with_fallback(start_port=otel_jaeger, max_tries=100)
            try:
                s_grpc.close()
            except:
                pass
            try:
                s_jaeger.close()
            except:
                pass
        else:
            # OTEL is already enabled – keep existing ports, do not reallocate.
            grpc_free = otel_grpc
            jaeger_free = otel_jaeger

        # Update values
        new_env_lines = []
        for line in env_lines:
            stripped = line.strip()
            if stripped.startswith("OTEL_DISABLED="):
                new_env_lines.append("OTEL_DISABLED=false\n")
            elif stripped.startswith("OTEL_HOST_GRPC_PORT="):
                new_env_lines.append(f"OTEL_HOST_GRPC_PORT={grpc_free}\n")
            elif stripped.startswith("OTEL_JAEGER_CLIENT_PORT="):
                new_env_lines.append(f"OTEL_JAEGER_CLIENT_PORT={jaeger_free}\n")
            else:
                new_env_lines.append(line)

        # Write back to .env
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_env_lines)
        except Exception as e:
            return JsonResponse({'status': 'danger', 'message': f'Failed to write to .env file: {str(e)}'}, status=500)

        # 2. Run docker compose recreate
        cmd = [
            "docker", "compose",
            "--profile", "db",
            "--profile", "heappe",
            "--profile", "initVault",
            "--profile", "vault",
            "--profile", "vaultagent",
            "--profile", "sshagent",
            "--profile", "staging",
            "--profile", "telemetry",
            "-p", instance_name,
            "up", "-d", "--force-recreate", "heappe", "datastagingapi", "otel-collector", "jaeger"
        ]
        result = execute_docker_compose(cmd, compose_dir)
        if result.returncode == 0:
            return JsonResponse({
                'status': 'success',
                'message': 'OpenTelemetry has been successfully enabled. Containers restarted.',
                'otel_grpc_port': grpc_free,
                'otel_jaeger_port': jaeger_free
            })
        else:
            return JsonResponse({'status': 'danger', 'message': f'Failed to restart containers: {result.stderr}'}, status=500)

    elif action == 'disable':
        # Update values
        new_env_lines = []
        for line in env_lines:
            stripped = line.strip()
            if stripped.startswith("OTEL_DISABLED="):
                new_env_lines.append("OTEL_DISABLED=true\n")
            else:
                new_env_lines.append(line)

        # Write back to .env
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_env_lines)
        except Exception as e:
            return JsonResponse({'status': 'danger', 'message': f'Failed to write to .env file: {str(e)}'}, status=500)

        # 2. Run docker compose stop & recreate without telemetry
        stop_cmd = [
            "docker", "compose",
            "--profile", "db",
            "--profile", "heappe",
            "--profile", "initVault",
            "--profile", "vault",
            "--profile", "vaultagent",
            "--profile", "sshagent",
            "--profile", "staging",
            "--profile", "telemetry",
            "-p", instance_name,
            "stop", "otel-collector", "jaeger"
        ]
        execute_docker_compose(stop_cmd, compose_dir)

        recreate_cmd = [
            "docker", "compose",
            "--profile", "db",
            "--profile", "heappe",
            "--profile", "initVault",
            "--profile", "vault",
            "--profile", "vaultagent",
            "--profile", "sshagent",
            "--profile", "staging",
            "-p", instance_name,
            "up", "-d", "--force-recreate", "heappe", "datastagingapi"
        ]
        result = execute_docker_compose(recreate_cmd, compose_dir)
        if result.returncode == 0:
            return JsonResponse({
                'status': 'success',
                'message': 'OpenTelemetry has been successfully disabled. Telemetry containers stopped.'
            })
        else:
            return JsonResponse({'status': 'danger', 'message': f'Failed to recreate API containers: {result.stderr}'}, status=500)

    else:
        return JsonResponse({'status': 'danger', 'message': f'Invalid action: {action}'}, status=400)


def handle_regenerate_configs_action(config, instance_name):
    """Regenerate configs (.env and appsettings.json) using update_init and restart all containers."""
    from datetime import datetime
    service = HEAppEDeployService(config)
    compose_dir = os.path.join(config.base_path, instance_name, "heappe-core")
    log_dir = os.path.join(config.base_path, instance_name, "app", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, "update.log")  # Write to update.log so the update progress modal displays it

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

        log_message("Starting configuration regeneration process...")
        _set_updating_status(instance_name, True)
        log_message("Database status set to updating.")

        log_message("Updating configuration files (.env and appsettings.json)...")
        clean_version = service.resolve_clean_version(config.repo_branch, instance_name=instance_name)
        service.update_init(instance_name=instance_name, version=clean_version)
        log_message(f"Configuration files successfully regenerated for version {clean_version} and merged with existing values.")

        log_message("Recreating and restarting containers with updated environment...")

        # Read .env to check if telemetry is enabled
        env_path = os.path.join(compose_dir, ".env")
        otel_disabled = True
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("OTEL_DISABLED="):
                            otel_disabled = (line.strip().split("=", 1)[1].strip().lower() == "true")
            except Exception:
                pass

        # Build start command with correct profiles
        cmd = [
            "docker", "compose",
            "--profile", "db",
            "--profile", "heappe",
            "--profile", "initVault",
            "--profile", "vault",
            "--profile", "vaultagent",
            "--profile", "sshagent",
            "--profile", "staging"
        ]
        if not otel_disabled:
            cmd.extend(["--profile", "telemetry"])

        cmd.extend(["-p", instance_name, "up", "-d", "--force-recreate"])

        log_message(f"Executing: {' '.join(cmd)}")
        result = execute_docker_compose(cmd, compose_dir)
        log_message(f"Docker Compose finished with return code {result.returncode}")
        if result.stdout:
            log_message(f"Docker stdout:\n{result.stdout}")
        if result.stderr:
            log_message(f"Docker stderr:\n{result.stderr}")

        if result.returncode != 0:
            log_message("ERROR: Docker Compose recreate failed.")
            _set_updating_status(instance_name, False)
            return result, f"Failed to restart containers: {result.stderr}", 'danger'

        log_message("SUCCESS: Configurations regenerated and containers restarted successfully.")
        _set_updating_status(instance_name, False)
        return result, "Configurations regenerated successfully.", 'success'
    except Exception as e:
        log_message(f"EXCEPTION: Regeneration error: {str(e)}")
        _set_updating_status(instance_name, False)
        return None, f"Regeneration error: {str(e)}", 'danger'


def _kick_vaultagent(instance_name):
    """Restart vaultagent container to immediately acquire new token without affecting other services."""
    try:
        client = get_docker_client()
        if client:
            for c in client.containers.list(all=True):
                if c.labels.get('com.docker.compose.project') == instance_name and 'vaultagent' in c.name.lower():
                    if c.status == 'running':
                        c.restart(timeout=5)
                        break
    except Exception:
        pass


def _kick_container(instance_name, service_keyword):
    """Restart a specific container by name keyword."""
    try:
        client = get_docker_client()
        if client:
            for c in client.containers.list(all=True):
                if c.labels.get('com.docker.compose.project') == instance_name and service_keyword in c.name.lower() and 'vault' not in c.name.lower():
                    if c.status == 'running':
                        c.restart(timeout=10)
                        break
    except Exception:
        pass


def _check_vault_sealed(port=8200):
    """Check if Vault is sealed via local HTTP API."""
    import urllib.request
    import urllib.error
    import json as pyjson
    url = f"http://127.0.0.1:{port}/v1/sys/seal-status"
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = pyjson.loads(resp.read().decode('utf-8'))
            return bool(data.get('sealed', False))
    except urllib.error.HTTPError as he:
        try:
            data = pyjson.loads(he.read().decode('utf-8'))
            return bool(data.get('sealed', True))
        except Exception:
            return True
    except Exception:
        return False


@login_required
def unseal_vault_api(request):
    """
    Unseal HashiCorp Vault in-place WITHOUT restarting HEAppE or other containers.
    Runs the 'initVault' profile one-shot container which performs the unseal operation,
    or directly submits an unseal key if provided by the user.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'danger', 'message': 'Only POST method is allowed.'}, status=405)

    instance_name = request.POST.get('instance_name') or request.session.get('chosen_instance', 'develop')
    base_path = "/opt/heappe-deployment/"
    compose_dir = os.path.join(base_path, instance_name, "heappe-core")

    unseal_key = request.POST.get('unseal_key', '').strip()
    restart_heappe = request.POST.get('restart_heappe', 'false').lower() == 'true'

    if not os.path.exists(compose_dir):
        alt_compose = os.path.join("/opt/heappe/", instance_name, "heappe-core")
        if os.path.exists(alt_compose):
            compose_dir = alt_compose

    vault_port = 8200
    env_path = os.path.join(compose_dir, ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    ls = line.strip()
                    for key in ("HOST_VAULT_PORT=", "VAULT_PORT=", "VAULT_HOST_PORT="):
                        if ls.startswith(key):
                            try:
                                vault_port = int(ls.split("=", 1)[1].strip())
                            except ValueError:
                                pass
        except Exception:
            pass

    # Method A: Custom unseal key submitted
    if unseal_key:
        try:
            import urllib.request
            import urllib.error
            import json as pyjson
            url = f"http://127.0.0.1:{vault_port}/v1/sys/unseal"
            req_data = pyjson.dumps({"key": unseal_key}).encode('utf-8')
            req = urllib.request.Request(url, data=req_data, headers={'Content-Type': 'application/json'}, method='POST')
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    res_json = pyjson.loads(resp.read().decode('utf-8'))
            except urllib.error.HTTPError as he:
                res_json = pyjson.loads(he.read().decode('utf-8'))

            is_sealed = res_json.get('sealed', True)
            if not is_sealed:
                _kick_vaultagent(instance_name)
                if restart_heappe:
                    _kick_container(instance_name, 'heappe')
                return JsonResponse({
                    'status': 'success',
                    'message': 'HashiCorp Vault was successfully unlocked using the provided unseal key (without restarting HEAppE)!',
                    'sealed': False
                })
            else:
                progress = f"Progress: {res_json.get('t', 0)} of {res_json.get('n', 0)} required keys."
                return JsonResponse({
                    'status': 'warning',
                    'message': f'Key accepted, but Vault is still sealed. {progress}',
                    'sealed': True
                })
        except Exception as e:
            return JsonResponse({'status': 'danger', 'message': f'Failed to unseal Vault via API: {str(e)}'}, status=500)

    # Method B: Automatic unseal via initVault profile
    if not os.path.exists(compose_dir):
        return JsonResponse({'status': 'danger', 'message': f'Deployment directory not found: {compose_dir}'}, status=404)

    cmd = [
        "docker", "compose",
        "--profile", "initVault",
        "-p", instance_name,
        "up", "--force-recreate", "--no-deps"
    ]

    try:
        result = execute_docker_compose(cmd, compose_dir, timeout=90)
        unseal_ok = (result.returncode == 0)

        time.sleep(1.5)
        _kick_vaultagent(instance_name)

        if restart_heappe:
            _kick_container(instance_name, 'heappe')

        is_sealed = _check_vault_sealed(vault_port)

        if not is_sealed:
            return JsonResponse({
                'status': 'success',
                'message': 'HashiCorp Vault unlocked successfully! HEAppE continues running without restart.',
                'sealed': False
            })
        else:
            if unseal_ok:
                return JsonResponse({
                    'status': 'success',
                    'message': 'The unseal command completed successfully! Vault is active.',
                    'sealed': False
                })
            return JsonResponse({
                'status': 'warning',
                'message': f'The unseal command finished with code {result.returncode}. If Vault remains locked, you can enter an unseal key manually.',
                'sealed': True,
                'stderr': result.stderr
            })
    except Exception as e:
        return JsonResponse({'status': 'danger', 'message': f'Error executing Vault unseal: {str(e)}'}, status=500)