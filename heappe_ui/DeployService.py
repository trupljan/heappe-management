import json
import hashlib
import logging
import os
import shutil
import subprocess
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass

from django.http import HttpResponse
from django.shortcuts import render

from heappe_ui.appsettings.generator import generate_appsettings_v6_0_0
from heappe_ui.models import InstanceCredentials

logger = logging.getLogger(__name__)


@dataclass
class HEAppEConfig:
    """Configuration for HEAppE deployment."""
    base_path: str = "/opt/heappe/"
    repo_url: str = "https://github.com/It4innovations/HEAppE.git"
    target_dir: str = "heappe-core"
    default_version: str = "v6.0.0"
    default_ip: str = "127.0.0.1"
    default_ports: Dict[str, int] = None

    def __post_init__(self):
        if self.default_ports is None:
            self.default_ports = {
                "mssql_port": 6000,
                "app_port": 5000,
                "data_staging_port": 5001,
                "local_port": 49005
            }


def get_instance_settings(instance_name:str= 'heappe_instance'):
    try:
        return InstanceCredentials.objects.get(
            instance_name=instance_name
        )
    except Exception:
        return None


class HEAppEDeployService:
    """Service to manage HEAppE deployment tasks."""

    def __init__(self, config: HEAppEConfig = None):
        """Initialize the service with optional configuration."""
        self.config = config or HEAppEConfig()
        self.logger = logger

    import os
    import shutil

    def create_directory_structure(self, instance_name, overwrite_existing=False):
        structure = [
            f"{instance_name}",
            f"{instance_name}/app/keys",
            f"{instance_name}/app/logs",
            f"{instance_name}/app/logs/Vault",
            f"{instance_name}/app/confs",
            f"{instance_name}/app/confs/vault/vault",
            f"{instance_name}/app/confs/vault/agent",
            f"{instance_name}/ssh_agent/keys"
        ]

        for folder in structure:
            path = os.path.join(self.config.base_path, folder)
            print(f"vytvarim cestu: {path}")
            if overwrite_existing and os.path.exists(path):
                shutil.rmtree(path, ignore_errors=True)
            os.makedirs(path, exist_ok=True)
            print(f"cesta vytvorena: {path}")

    def clone_repository(self, instance_name: str, overwrite_existing: bool = False) -> None:
        """Clone HEAppE repository into the project directory."""
        project_path = os.path.join(self.config.base_path, instance_name)
        clone_path = os.path.join(project_path, self.config.target_dir)

        if os.path.exists(clone_path) and not overwrite_existing:
            self.logger.info(f"Repository already exists at {clone_path}, skipping clone")
            return

        if overwrite_existing and os.path.exists(clone_path):
            shutil.rmtree(clone_path, ignore_errors=True)
            self.logger.info(f"Removed existing repository at: {clone_path}")

        self.logger.info(f"Cloning {self.config.repo_url} into {clone_path}...")
        print(f"Cloning {self.config.repo_url} into {clone_path}...")
        try:
            os.makedirs(clone_path, exist_ok=True)
            subprocess.run(
                ["git", "clone", self.config.repo_url, clone_path],
                check=True,
                capture_output=True,
                text=True
            )
            self.logger.info(f"Repository cloned successfully to {clone_path}")
            print(f"Repository cloned successfully to {clone_path}")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error cloning repository: {e.stderr}")
            raise RuntimeError(f"Repository cloning failed: {e}")

    def generate_env_file(
            self,
            instance_name: str,
            vault_password: str,
            sa_password: str,
            ports: Optional[Dict[str, int]] = None,
            overwrite_existing: bool = False
    ) -> str:
        """Generate .env file for HEAppE project."""
        ports = ports or self.config.default_ports
        content = f"""COMPOSE_instance_name=heappe
INSTANCE_NAME={instance_name}

## HashiCorp Vault
VAULT_FILE_DIR_PATH={self.config.base_path}{instance_name}
SHARED_VAULT_FILE=false
SHARED_VAULT_FILE_NAME=credentials_{instance_name.lower()}
VAULT_PASSWORD={vault_password}
BASE_PATH={self.config.base_path}{instance_name}/app/confs

HOST_SSHAGENT_NAME=sshagent-{instance_name}
HOST_SSHAGENT_HOST_MAP_FOLD_PATH={self.config.base_path}{instance_name}/ssh_agent/keys
HOST_SSHAGENT_CONTAINER_MAP_FOLD_PATH=/opt/heappe/sshagent_keys:ro

HOST_MSSQL_NAME=mssql-{instance_name}
HOST_MSSQL_PORT={ports['mssql_port']}
HOST_MSSQL_PASSWORD={sa_password}

HOST_APP_NAME=heappe-{instance_name}
HOST_APP_PORT={ports['app_port']}
HOST_APP_HOST_MAP_FOLD_NAME={self.config.base_path}{instance_name}/app
HOST_APP_CONTAINER_MAP_FOLD_PATH=/opt/heappe

HOST_DATA_STAGING_NAME=datastaging-{instance_name}
HOST_DATA_STAGING_PORT={ports['data_staging_port']}
HOST_DATA_STAGING_HOST_MAP_FOLD_NAME={self.config.base_path}{instance_name}/app
HOST_DATA_STAGING_CONTAINER_MAP_FOLD_PATH=/opt/heappe

# Only for Local Cluster mode
HOST_LOCAL_NAME=localhpc-{instance_name}
HOST_LOCAL_PORT={ports['local_port']}
"""
        output_dir = os.path.join(self.config.base_path, instance_name, self.config.target_dir)
        output_path = os.path.join(output_dir, ".env")

        try:
            if os.path.exists(output_path) and not overwrite_existing:
                self.logger.info(f".env file already exists at {output_path}, skipping generation")
                return output_path

            if os.path.exists(output_path) and overwrite_existing:
                os.remove(output_path)
                self.logger.info(f"Removed existing .env file: {output_path}")

            os.makedirs(output_dir, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.logger.info(f".env file generated at: {output_path}")
            return output_path
        except OSError as e:
            self.logger.error(f"Failed to generate .env file: {e}")
            raise RuntimeError(f".env file generation failed: {e}")

    def generate_seed_file(
            self,
            username: str,
            password: str,
            instance_name: str,
            overwrite_existing: bool = False
    ) -> Dict[str, Any]:
        """Generate seed.njson file for HEAppE instance."""
        salt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        salted_password = password + salt
        password_hash = hashlib.sha512(salted_password.encode("utf-8")).hexdigest().upper()

        seed_data = {
            "MiddlewareContextSettings": {
                "AdaptorUsers": [
                    {
                        "Id": 1,
                        "Username": username,
                        "Password": password_hash,
                        "CreatedAt": salt,
                        "ModifiedAt": None
                    }
                ],
                "AdaptorUserGroups": [
                    {
                        "Id": 1,
                        "Name": f"{username}_group",
                        "Description": f"Default group for {username}",
                        "ProjectId": None
                    }
                ],
                "AdaptorUserRoles": [
                    {"Id": 1, "Name": "Administrator",
                     "Description": "HEAppE administrator role with access to the entire system."},
                    {"Id": 2, "Name": "Maintainer",
                     "Description": "HEAppE maintainer role for getting information about actual HEAppE status."},
                    {"Id": 3, "Name": "Submitter", "Description": "Standard user, can submit and check his own jobs."},
                    {"Id": 4, "Name": "GroupReporter",
                     "Description": "Users with this role can report in assigned groups."},
                    {"Id": 5, "Name": "Reporter",
                     "Description": "Users with this role can watch other jobs in the same group."},
                    {"Id": 6, "Name": "ManagementAdmin",
                     "Description": "User with this role can create new project and use management API."},
                    {"Id": 7, "Name": "Manager",
                     "Description": "User with this role can manage command templates, can submit and check his own jobs."}
                ],
                "AdaptorUserUserGroupRoles": [
                    {
                        "AdaptorUserId": 1,
                        "AdaptorUserGroupId": 1,
                        "AdaptorUserRoleId": 1,
                        "CreatedAt": salt,
                        "ModifiedAt": None,
                        "IsDeleted": False
                    }
                ]
            }
        }

        output_dir = os.path.join(self.config.base_path, instance_name, "app", "confs")
        output_path = os.path.join(output_dir, "seed.njson")

        try:
            if os.path.exists(output_path) and not overwrite_existing:
                self.logger.info(f"seed.njson file already exists at {output_path}, skipping generation")
                return seed_data

            if os.path.exists(output_path) and overwrite_existing:
                os.remove(output_path)
                self.logger.info(f"Removed existing seed.njson file: {output_path}")

            os.makedirs(output_dir, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(seed_data, f, indent=3)
            self.logger.info(f"Seed file generated at: {output_path}")
            return seed_data
        except OSError as e:
            self.logger.error(f"Failed to generate seed.njson file: {e}")
            raise RuntimeError(f"seed.njson file generation failed: {e}")

    def generate_appsettings_file(
            self,
            instance_name: str,
            sa_password: str,
            port: int = 5000,
            automigrate: bool = True,
            version: str = None,
            deployed_ip: str = None,
            overwrite_existing: bool = False
    ) -> Dict[str, Any]:
        """Generate appsettings.json file for HEAppE instance."""
        version = version or self.config.default_version
        deployed_ip = deployed_ip or self.config.default_ip

        appsettings = generate_appsettings_v6_0_0(
            instance_name=instance_name,
            sa_password=sa_password,
            port=port,
            automigrate=automigrate,
            version=version,
            deployed_ip=deployed_ip
        )

        output_dir = os.path.join(self.config.base_path, instance_name, "app", "confs")
        output_path = os.path.join(output_dir, "appsettings.json")

        try:
            if os.path.exists(output_path) and not overwrite_existing:
                self.logger.info(f"appsettings.json file already exists at {output_path}, skipping generation")
                return appsettings

            if os.path.exists(output_path) and overwrite_existing:
                os.remove(output_path)
                self.logger.info(f"Removed existing appsettings.json file: {output_path}")

            os.makedirs(output_dir, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(appsettings, f, indent=3)
            self.logger.info(f"Appsettings file generated at: {output_path}")
            return appsettings
        except OSError as e:
            self.logger.error(f"Failed to generate appsettings.json file: {e}")
            raise RuntimeError(f"appsettings.json file generation failed: {e}")

    def save_instance_settings(self, instance_name, heappe_host, heappe_port, heappe_login, heappe_password,
                             log_db_host, log_db_port,
                             log_db_user, log_db_password,
                             log_db_database):
        obj, created = InstanceCredentials.objects.update_or_create(
            instance_name=instance_name,
            defaults={
                "heappe_host": heappe_host,
                "heappe_port": heappe_port,
                "heappe_login": heappe_login,
                "heappe_password": heappe_password,
                "log_db_host": log_db_host,
                "log_db_port": log_db_port,
                "log_db_user": log_db_user,
                "log_db_password": log_db_password,
                "log_db_database": log_db_database,
            }
        )
        return obj, created

    def deploy_init(
            self,
            instance_name: str,
            username: str,
            password: str,
            vault_password: str,
            sa_password: str,
            overwrite_existing: bool = False,
            ports: Optional[Dict[str, int]] = None,
            version: Optional[str] = None,
            deployed_ip: Optional[str] = None
    ) -> Dict[str, Any]:
        """Initialize HEAppE deployment with option to overwrite existing resources."""
        try:
            self.logger.info(
                f"Starting HEAppE deployment initialization for instance: {instance_name}")

            # Create directory structure
            self.create_directory_structure(instance_name=instance_name,overwrite_existing=overwrite_existing)

            # Clone repository
            self.clone_repository(instance_name, overwrite_existing)

            # Generate configuration files
            env_path = self.generate_env_file(instance_name, vault_password, sa_password, ports, overwrite_existing)
            seed_data = self.generate_seed_file(username, password, instance_name, overwrite_existing)
            appsettings = self.generate_appsettings_file(
                instance_name=instance_name,
                port=ports.get("app_port") if ports else 5000,
                version=version,
                deployed_ip=deployed_ip,
                sa_password=sa_password,
                automigrate=True,
                overwrite_existing=overwrite_existing
            )

            self.logger.info("HEAppE deployment initialization completed successfully")
            self.save_instance_settings(instance_name=instance_name,
                                        heappe_host=deployed_ip,
                                        heappe_login=username,
                                        heappe_password=password,
                                        log_db_host=deployed_ip or self.config.default_ip,
                                        heappe_port=ports.get("app_port") if ports else 5000,
                                        log_db_port=str(ports.get("mssql_port") if ports else 6000),
                                        log_db_user="SA",
                                        log_db_password=sa_password,
                                        log_db_database="heappe-monitoring")

            return {
                "status": "success",
                "env_path": env_path,
                "seed_data": seed_data,
                "appsettings": appsettings
            }
        except Exception as e:
            self.logger.error(f"Deployment initialization failed: {e}")
            return {"status": "error", "message": str(e)}