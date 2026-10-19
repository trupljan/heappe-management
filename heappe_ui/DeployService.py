import json
import hashlib
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass

from django.http import HttpResponse
from django.shortcuts import render

from heappe_ui.appsettings.generator import (
    generate_appsettings_v6_0_0,
    generate_appsettings_data_staging_v6_0_0,
    generate_appsettings_v6_1_0,
    generate_appsettings_data_staging_v6_1_0,
    generate_appsettings_v6_2_0,
    generate_appsettings_data_staging_v6_2_0,
    generate_appsettings_v6_2_1,
    generate_appsettings_data_staging_v6_2_1,
    generate_appsettings_v6_4_0,
    generate_appsettings_data_staging_v6_4_0,
    generate_appsettings_v6_4_17,
    generate_appsettings_data_staging_v6_4_17,
    generate_appsettings_v6_5_0,
    generate_appsettings_data_staging_v6_5_0,
    generate_appsettings_v6_6_0,
    generate_appsettings_data_staging_v6_6_0,
)
from heappe_ui.view.utils import clean_ver

from heappe_ui.models import InstanceCredentials

logger = logging.getLogger(__name__)


@dataclass
class HEAppEConfig:
    """Configuration for HEAppE deployment."""
    base_path: str = "/opt/heappe/"
    repo_url: str = "https://github.com/It4innovations/HEAppE.git"
    repo_branch: str = "master"
    target_dir: str = "heappe-core"
    default_version: str = "v6.0.0"
    default_ip: str = "127.0.0.1"
    default_ports: Dict[str, int] = None

    def __post_init__(self):
        defaults = {
            "mssql_port": 6000,
            "app_port": 5000,
            "data_staging_port": 5001,
            "local_port": 49005,
            "otel_grpc_port": 4317,
            "otel_jaeger_port": 16686
        }
        if self.default_ports is None:
            self.default_ports = defaults
        else:
            for k, v in defaults.items():
                if k not in self.default_ports:
                    self.default_ports[k] = v


def get_instance_settings(instance_name:str= 'heappe_instance'):
    try:
        return InstanceCredentials.objects.get(
            instance_name=instance_name
        )
    except Exception:
        return None


def extract_version_from_changelog(repo_or_changelog_path: Optional[str]) -> Optional[str]:
    """
    Extract the latest release version from a CHANGELOG file.
    Searches for files like CHANGELOG.md, changelog.md, etc.
    Parses version headers like '## [6.5.2]', '## v6.5.2', '## Version 6.5.2', etc.
    Skips 'Unreleased' sections.
    """
    if not repo_or_changelog_path:
        return None

    file_path = repo_or_changelog_path
    if os.path.isdir(repo_or_changelog_path):
        candidate_names = [
            "CHANGELOG.md", "changelog.md", "CHANGELOG", "ChangeLog.md",
            "ChangeLog", "CHANGES.md", "changes.md", "HISTORY.md", "history.md"
        ]
        found = None
        for name in candidate_names:
            p = os.path.join(repo_or_changelog_path, name)
            if os.path.isfile(p):
                found = p
                break
        if not found:
            return None
        file_path = found

    if not os.path.isfile(file_path):
        return None

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("<!--"):
                    continue

                # Skip unreleased / work in progress sections
                if "unreleased" in line.lower() or "wip" in line.lower():
                    continue

                # Check for bracketed version: [6.5.2] or [v6.5.2]
                m_bracket = re.search(r'\[[vV]?(\d+\.\d+(?:\.\d+)*)\]', line)
                if m_bracket:
                    ver = m_bracket.group(1)
                    return f"v{ver}"

                # Check for header lines starting with # (e.g. ## 6.5.2, ### v6.5.2, # Version 6.5.2)
                if line.startswith("#"):
                    m_ver = re.search(r'(?:version\s*|[vV])?(\d+\.\d+(?:\.\d+)*)', line, re.IGNORECASE)
                    if m_ver:
                        ver = m_ver.group(1)
                        if ver.count(".") >= 1:
                            return f"v{ver}"

                # Check for lines starting directly with version: Version 6.5.2 or v6.5.2
                m_direct = re.match(r'^(?:Version\s+|[vV])?(\d+\.\d+(?:\.\d+)*)\b', line, re.IGNORECASE)
                if m_direct:
                    ver = m_direct.group(1)
                    if ver.count(".") >= 1:
                        return f"v{ver}"
    except Exception as e:
        logger.warning(f"Error reading changelog from {file_path}: {e}")

    return None


def resolve_clean_version(
        version_or_ref: Optional[str] = None,
        compose_dir: Optional[str] = None,
        old_version: Optional[str] = None,
        default_version: str = "v6.5.0"
) -> str:
    """
    Resolve a branch, tag, or version string into a clean semantic version string
    (e.g., 'v6.5.0', 'v6.4.17') without slashes or non-version branch names.
    This ensures ASP.NET Core Swagger/OpenAPI route '/swagger/{Version}/swagger.json'
    and Swagger UI operate correctly without 404 route errors.
    """
    # 1. Direct semantic version check (e.g. "v6.5.0", "6.4.17", "V6.3.3", "v6.2.2")
    if version_or_ref:
        v_str = str(version_or_ref).strip()
        if re.match(r'^[vV]?\d+(?:\.\d+)+$', v_str):
            return v_str

    # 2. Check if version_or_ref contains a semantic version tag (e.g. "release/v6.5.0", "tags/v6.4.17")
    if version_or_ref:
        v_str = str(version_or_ref).strip()
        m = re.search(r'[vV]\d+\.\d+(?:\.\d+)*', v_str)
        if not m:
            m = re.search(r'(?<=/)\d+\.\d+(?:\.\d+)*', v_str)
        if m:
            val = m.group(0)
            return val if val.startswith(('v', 'V')) else f"v{val}"

    # 3. Check CHANGELOG in compose_dir (e.g. when branch is 'develop', 'master', etc.)
    if compose_dir and os.path.exists(compose_dir):
        changelog_version = extract_version_from_changelog(compose_dir)
        if changelog_version:
            return changelog_version

    # 4. If compose_dir is provided and has a git repository, query git for nearest version tag
    if compose_dir and os.path.exists(os.path.join(compose_dir, ".git")):
        for cmd in [
            ["git", "describe", "--tags", "--match", "v[0-9]*", "--match", "[0-9]*", "--abbrev=0"],
            ["git", "describe", "--tags", "--abbrev=0"]
        ]:
            try:
                res = subprocess.run(cmd, cwd=compose_dir, capture_output=True, text=True, check=False, timeout=5)
                if res.returncode == 0 and res.stdout.strip():
                    tag = res.stdout.strip()
                    if re.match(r'^[vV]?\d+(?:\.\d+)+$', tag):
                        return tag
                    m_tag = re.search(r'[vV]?\d+\.\d+(?:\.\d+)*', tag)
                    if m_tag:
                        val = m_tag.group(0)
                        return val if val.startswith(('v', 'V')) else f"v{val}"
            except Exception:
                pass

        # Try finding highest tag in git repository
        try:
            res = subprocess.run(
                ["git", "tag", "-l", "v[0-9]*", "--sort=-v:refname"],
                cwd=compose_dir, capture_output=True, text=True, check=False, timeout=5
            )
            if res.returncode == 0 and res.stdout.strip():
                first_tag = res.stdout.strip().splitlines()[0].strip()
                if re.match(r'^[vV]?\d+(?:\.\d+)+$', first_tag):
                    return first_tag
        except Exception:
            pass

    # 5. Fallback to existing old_version if it is a valid semantic version (and not "unknown")
    if old_version and old_version.lower() not in ("unknown", "none", ""):
        old_str = str(old_version).strip()
        if re.match(r'^[vV]?\d+(?:\.\d+)+$', old_str):
            return old_str
        m_old = re.search(r'[vV]?\d+\.\d+(?:\.\d+)*', old_str)
        if m_old:
            val = m_old.group(0)
            return val if val.startswith(('v', 'V')) else f"v{val}"

    # 6. Default fallback
    return default_version or "v6.5.0"


class HEAppEDeployService:
    """Service to manage HEAppE deployment tasks."""

    def __init__(self, config: HEAppEConfig = None):
        """Initialize the service with optional configuration."""
        self.config = config or HEAppEConfig()
        self.logger = logger

    def resolve_clean_version(
            self,
            version_or_ref: Optional[str] = None,
            instance_name: Optional[str] = None,
            old_version: Optional[str] = None
    ) -> str:
        """Resolve branch or version to a clean semver string for this instance."""
        compose_dir = None
        if instance_name:
            compose_dir = os.path.join(self.config.base_path, instance_name, self.config.target_dir)
        return resolve_clean_version(
            version_or_ref=version_or_ref,
            compose_dir=compose_dir,
            old_version=old_version,
            default_version="v6.5.0"
        )

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
            print(f"Creating path: {path}")
            if overwrite_existing and os.path.exists(path):
                shutil.rmtree(path, ignore_errors=True)
            os.makedirs(path, exist_ok=True)
            print(f"Path created: {path}")

        # Create host directory for OpenTelemetry Collector logs
        try:
            os.makedirs("/var/log/otel", exist_ok=True)
            self.logger.info("Host directory /var/log/otel successfully initialized.")
        except Exception as e:
            self.logger.warning(f"Could not create /var/log/otel directory on host: {e}")

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
                ["git", "clone", "--branch", self.config.repo_branch, self.config.repo_url, clone_path],
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
        """Generate .env file for HEAppE project using separate build and save methods."""
        content = self.build_env_content(instance_name, vault_password, sa_password, ports)
        return self.save_env_file(instance_name, content, overwrite_existing)

    def build_env_content(
            self,
            instance_name: str,
            vault_password: str,
            sa_password: str,
            ports: Optional[Dict[str, int]] = None
    ) -> str:
        """Build content for .env file for HEAppE project."""
        # Merge provided ports with defaults (provided ports take priority)
        merged_ports = self.config.default_ports.copy()
        if ports:
            merged_ports.update(ports)
        ports = merged_ports

        otel_grpc = ports.get('otel_grpc_port', 4317)
        otel_jaeger = ports.get('otel_jaeger_port', 16686)

        # Read OTEL_DISABLED from existing or archived .env if present, otherwise default to true
        otel_disabled = "true"
        target_dir = os.path.join(self.config.base_path, instance_name, self.config.target_dir)
        env_path = os.path.join(target_dir, ".env")

        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("OTEL_DISABLED="):
                            otel_disabled = line.strip().split("=", 1)[1].strip()
            except Exception:
                pass
        else:
            try:
                if os.path.exists(target_dir):
                    archives = [os.path.join(target_dir, f) for f in os.listdir(target_dir) if f.startswith(".env_")]
                    if archives:
                        latest_archive = max(archives, key=os.path.getmtime)
                        with open(latest_archive, "r", encoding="utf-8") as f:
                            for line in f:
                                if line.strip().startswith("OTEL_DISABLED="):
                                    otel_disabled = line.strip().split("=", 1)[1].strip()
            except Exception:
                pass

        return f"""COMPOSE_instance_name=heappe
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
HOST_MSSQL_PID=Express
HOST_MSSQL_MEMORY_LIMIT_MB=4096
HOST_MSSQL_CPUS=4
HOST_MSSQL_MEMORY=6G

HOST_APP_NAME=heappe-{instance_name}
HOST_APP_PORT={ports['app_port']}
HOST_APP_HOST_MAP_FOLD_NAME={self.config.base_path}{instance_name}/app
HOST_APP_CONTAINER_MAP_FOLD_PATH=/opt/heappe

HOST_DATA_STAGING_NAME=datastaging-{instance_name}
HOST_DATA_STAGING_PORT={ports['data_staging_port']}
HOST_DATA_STAGING_HOST_MAP_FOLD_NAME={self.config.base_path}{instance_name}/app
HOST_DATA_STAGING_CONTAINER_MAP_FOLD_PATH=/opt/heappe

DATABASE_FULL_BACKUP_HOST_MAP_FOLD_NAME={self.config.base_path}{instance_name}/backups/database
DATABASE_LOGS_BACKUP_HOST_MAP_FOLD_NAME={self.config.base_path}{instance_name}/backups/database/logs

HOST_KRB5_CONF_PATH={self.config.base_path}{instance_name}/app/confs/krb5.conf

# Only for Local Cluster mode
HOST_LOCAL_NAME=localhpc-{instance_name}
HOST_LOCAL_PORT={ports['local_port']}

# OpenTelemetry configuration
OTEL_DISABLED={otel_disabled}
OTEL_HOST_GRPC_PORT={otel_grpc}
OTEL_JAEGER_CLIENT_PORT={otel_jaeger}
OTEL_SERVICE_SUFFIX_ID=0

PWD={self.config.base_path}{instance_name}/heappe-core
"""

    def save_env_file(
            self,
            instance_name: str,
            content: str,
            overwrite_existing: bool = False
    ) -> str:
        """Save .env content to file."""
        output_dir = os.path.join(self.config.base_path, instance_name, self.config.target_dir)
        output_path = os.path.join(output_dir, ".env")

        try:
            if os.path.exists(output_path):
                if overwrite_existing:
                    os.remove(output_path)
                    self.logger.info(f"Removed existing .env file: {output_path}")
                else:
                    self.logger.info(f".env file already exists at {output_path}, skipping generation")
                    return output_path

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

    def _get_generators_for_version(self, version: str):
        v_clean = clean_ver(version)
        if not version or v_clean == [0, 0, 0] or not any(v_clean):
            # Branch names without version numbers (e.g. master, main, development) default to latest generator
            return generate_appsettings_v6_6_0, generate_appsettings_data_staging_v6_6_0
        if v_clean < [6, 1, 0]:
            return generate_appsettings_v6_0_0, generate_appsettings_data_staging_v6_0_0
        elif v_clean < [6, 2, 0]:
            return generate_appsettings_v6_1_0, generate_appsettings_data_staging_v6_1_0
        elif v_clean == [6, 2, 0]:
            return generate_appsettings_v6_2_0, generate_appsettings_data_staging_v6_2_0
        elif v_clean < [6, 4, 0]:
            return generate_appsettings_v6_2_1, generate_appsettings_data_staging_v6_2_1
        elif v_clean < [6, 4, 17]:
            return generate_appsettings_v6_4_0, generate_appsettings_data_staging_v6_4_0
        elif v_clean < [6, 5, 0]:
            return generate_appsettings_v6_4_17, generate_appsettings_data_staging_v6_4_17
        elif v_clean < [6, 6, 0]:
            return generate_appsettings_v6_5_0, generate_appsettings_data_staging_v6_5_0
        else:
            return generate_appsettings_v6_6_0, generate_appsettings_data_staging_v6_6_0

    def generate_appsettings_and_merge_with_old(self, old_appsettings: dict, version: str) -> dict:
        """Generate appsettings.json and merge with old settings."""
        # This is a placeholder for the actual implementation
        # You would generate new appsettings and then merge with old_appsettings
        clean_version = self.resolve_clean_version(version)
        app_fn, _ = self._get_generators_for_version(clean_version)

        new_appsettings = app_fn(
            instance_name="instance",
            sa_password="Passw0rd",
            port=5000,
            automigrate=True,
            version=clean_version,
            deployed_ip="localhost"
        )

        return self.merge_keep_old(old_appsettings, new_appsettings)

    def generate_appsettings_files(
            self,
            instance_name: str,
            sa_password: str,
            port_app: int = 5000,
            port_staging: int = 5001,
            data_staging_token: str = "changeme",
            automigrate: bool = True,
            version: str = None,
            deployed_ip: str = None,
            overwrite_existing: bool = False
    ) -> Dict[str, Any]:
        """Generate appsettings.json and appsettings-data.json files for HEAppE instance."""
        clean_version = self.resolve_clean_version(version or self.config.default_version, instance_name=instance_name)
        deployed_ip = deployed_ip or self.config.default_ip

        print(f"Generating appsettings for version: {clean_version}")

        app_fn, data_fn = self._get_generators_for_version(clean_version)

        appsettings = app_fn(
            instance_name=instance_name,
            sa_password=sa_password,
            port=port_app,
            automigrate=automigrate,
            version=clean_version,
            deployed_ip=deployed_ip
        )

        appsettings_data_staging = data_fn(
            instance_name=instance_name,
            sa_password=sa_password,
            data_staging_token=data_staging_token,
            port=port_staging,
            version=clean_version
        )

        print(f"Generated appsettings: {appsettings}")

        output_dir = os.path.join(self.config.base_path, instance_name, "app", "confs")
        output_path_app = os.path.join(output_dir, "appsettings.json")
        output_path_staging = os.path.join(output_dir, "appsettings-data.json")

        os.makedirs(output_dir, exist_ok=True)

        results = {}

        # Handle appsettings.json
        try:
            if os.path.exists(output_path_app) and not overwrite_existing:
                self.logger.info(f"appsettings.json file already exists at {output_path_app}, skipping generation")
            else:
                if os.path.exists(output_path_app) and overwrite_existing:
                    os.remove(output_path_app)
                    self.logger.info(f"Removed existing appsettings.json file: {output_path_app}")

                with open(output_path_app, "w", encoding="utf-8") as f:
                    json.dump(appsettings, f, indent=3)
                self.logger.info(f"Appsettings file generated at: {output_path_app}")
            results['appsettings'] = appsettings
        except OSError as e:
            self.logger.error(f"Failed to generate appsettings.json file: {e}")
            print(f"Failed to generate appsettings.json file: {e}")
            raise RuntimeError(f"appsettings.json file generation failed: {e}")

        # Handle appsettings-data.json
        try:
            if os.path.exists(output_path_staging) and not overwrite_existing:
                self.logger.info(
                    f"appsettings-data.json file already exists at {output_path_staging}, skipping generation")
            else:
                if os.path.exists(output_path_staging) and overwrite_existing:
                    os.remove(output_path_staging)
                    self.logger.info(f"Removed existing appsettings-data.json file: {output_path_staging}")

                with open(output_path_staging, "w", encoding="utf-8") as f:
                    json.dump(appsettings_data_staging, f, indent=3)
                self.logger.info(f"Appsettings-data file generated at: {output_path_staging}")
            results['appsettings_data_staging'] = appsettings_data_staging
        except OSError as e:
            self.logger.error(f"Failed to generate appsettings-data.json file: {e}")
            raise RuntimeError(f"appsettings-data.json file generation failed: {e}")

        return results

    def save_instance_settings(self, instance_name, heappe_host, heappe_port, heappe_login, heappe_password,
                             log_db_host, log_db_port,
                             log_db_user, log_db_password,
                             log_db_database, is_deployed):
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
                "is_deployed": is_deployed,
                "deployment_date_time": datetime.now()
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
            data_staging_token: str,
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
            clean_version = self.resolve_clean_version(version, instance_name=instance_name)
            env_path = self.generate_env_file(instance_name, vault_password, sa_password, ports, overwrite_existing)
            seed_data = self.generate_seed_file(username, password, instance_name, overwrite_existing)
            appsettings = self.generate_appsettings_files(
                instance_name=instance_name,
                port_app=ports.get("app_port") if ports else 5000,
                port_staging=ports.get("data_staging_port") if ports else 5001,
                version=clean_version,
                deployed_ip=deployed_ip,
                sa_password=sa_password,
                data_staging_token=data_staging_token,
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
                                        log_db_database="heappe-monitoring",
                                        is_deployed=False
                                        )

            return {
                "status": "success",
                "env_path": env_path,
                "seed_data": seed_data,
                "appsettings": appsettings["appsettings"],
                "appsettings_data_staging": appsettings["appsettings_data_staging"],
                "instance_settings": get_instance_settings(instance_name)
            }
        except Exception as e:
            self.logger.error(f"Deployment initialization failed: {e}")
            return {"status": "error", "message": str(e)}

    def merge_keep_old(self, old: dict, new: dict) -> dict:
        result = new.copy()  # start with new JSON
        for key, value in old.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self.merge_keep_old(value, result[key])  # recursive dict merge
            elif key in result and isinstance(result[key], list) and isinstance(value, list):
                if key == "GeneralRules":
                    merged_list = [dict(item) if isinstance(item, dict) else item for item in value]
                    existing_endpoints = {r.get('Endpoint') for r in merged_list if isinstance(r, dict)}
                    new_missing_rules = [dict(r) for r in result[key] if isinstance(r, dict) and r.get('Endpoint') not in existing_endpoints]
                    catch_all_idx = None
                    for idx, r in enumerate(merged_list):
                        if isinstance(r, dict) and r.get('Endpoint') == '*':
                            catch_all_idx = idx
                            break
                    if catch_all_idx is not None:
                        merged_list[catch_all_idx:catch_all_idx] = new_missing_rules
                    else:
                        merged_list = new_missing_rules + merged_list
                    result[key] = merged_list
                else:
                    result[key] = value
            elif key == "ExtendedUserInfoV2Endpoint" and value == "/api/v2/users/me/extended" and key in result:
                pass
            elif key == "CommandTemplatePermissionsV2Endpoint" and value == "/api/v2/heappe/command-template-permissions/" and key in result:
                pass
            else:
                result[key] = value  # use value from old JSON
        return result

    def update_init(
                self,
                instance_name: str,
                version: str
        ) -> Dict[str, Any]:
            """Initialize HEAppE update with option to merge with existing resources."""
            try:
                self.logger.info(
                    f"Starting HEAppE update initialization for instance: {instance_name}")
                # load old appsettings from disc and merge with new settings
                old_appsettings_path = os.path.join(self.config.base_path, instance_name, "app", "confs", "appsettings.json")
                if os.path.exists(old_appsettings_path):
                    with open(old_appsettings_path, "r", encoding="utf-8") as f:
                        old_appsettings = json.load(f)
                else:
                    old_appsettings = {}

                old_version = old_appsettings.get("ApplicationAPISettings", {}).get("DeploymentSettings", {}).get("Version", "")
                old_version = old_version or "unknown"
                clean_version = self.resolve_clean_version(version, instance_name=instance_name, old_version=old_version)

                # change version in old appsettings to the clean version
                if clean_version:
                    if "ApplicationAPISettings" not in old_appsettings:
                        old_appsettings["ApplicationAPISettings"] = {}
                    if "DeploymentSettings" not in old_appsettings["ApplicationAPISettings"]:
                        old_appsettings["ApplicationAPISettings"]["DeploymentSettings"] = {}
                    old_appsettings["ApplicationAPISettings"]["DeploymentSettings"]["Version"] = clean_version
                    if "SwaggerDocSettings" not in old_appsettings["ApplicationAPISettings"]:
                        old_appsettings["ApplicationAPISettings"]["SwaggerDocSettings"] = {}
                    old_appsettings["ApplicationAPISettings"]["SwaggerDocSettings"]["Description"] = f"HEAppE middleware API {clean_version}"

                # Generate configuration files
                appsettings_new = self.generate_appsettings_and_merge_with_old(old_appsettings, clean_version)

                # archive old appsettings
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                safe_old_version = re.sub(r'[/\\:\s]+', '_', old_version)
                if os.path.exists(old_appsettings_path):
                    archived_appsettings_path = os.path.join(self.config.base_path, instance_name, "app", "confs", f"appsettings_{safe_old_version}_{timestamp}.json")
                    shutil.copy2(old_appsettings_path, archived_appsettings_path)
                    self.logger.info(f"Archived old appsettings to: {archived_appsettings_path}")
                # save new merged appsettings
                output_dir = os.path.join(self.config.base_path, instance_name, "app", "confs")
                output_path_app = os.path.join(output_dir, "appsettings.json")
                with open(output_path_app, "w", encoding="utf-8") as f:
                    json.dump(appsettings_new, f, indent=3)
                self.logger.info(f"Updated appsettings file generated at: {output_path_app}")

                # archive and update appsettings-data.json if exists
                old_data_staging_path = os.path.join(self.config.base_path, instance_name, "app", "confs", "appsettings-data.json")
                if os.path.exists(old_data_staging_path):
                    try:
                        with open(old_data_staging_path, "r", encoding="utf-8") as f:
                            old_data_staging = json.load(f)
                        old_ds_version = old_data_staging.get("ApplicationAPIConfiguration", {}).get("DeploymentConfiguration", {}).get("Version", "") or "unknown"
                        safe_old_ds_version = re.sub(r'[/\\:\s]+', '_', old_ds_version)
                        archived_ds_path = os.path.join(self.config.base_path, instance_name, "app", "confs", f"appsettings-data_{safe_old_ds_version}_{timestamp}.json")
                        shutil.copy2(old_data_staging_path, archived_ds_path)
                        self.logger.info(f"Archived old appsettings-data to: {archived_ds_path}")

                        if clean_version:
                            if "ApplicationAPIConfiguration" not in old_data_staging:
                                old_data_staging["ApplicationAPIConfiguration"] = {}
                            if "DeploymentConfiguration" not in old_data_staging["ApplicationAPIConfiguration"]:
                                old_data_staging["ApplicationAPIConfiguration"]["DeploymentConfiguration"] = {}
                            old_data_staging["ApplicationAPIConfiguration"]["DeploymentConfiguration"]["Version"] = clean_version

                        _, data_fn = self._get_generators_for_version(clean_version)
                        new_ds = data_fn(
                            instance_name=instance_name,
                            sa_password="",
                            data_staging_token="",
                            port=5001,
                            version=clean_version
                        )
                        merged_ds = self.merge_keep_old(old_data_staging, new_ds)
                        with open(old_data_staging_path, "w", encoding="utf-8") as f:
                            json.dump(merged_ds, f, indent=3)
                        self.logger.info(f"Updated appsettings-data.json generated at: {old_data_staging_path}")
                    except Exception as e:
                        self.logger.warning(f"Could not update appsettings-data.json during update_init: {e}")

                # Create host directory for OpenTelemetry Collector logs during update
                try:
                    os.makedirs("/var/log/otel", exist_ok=True)
                except Exception as e:
                    self.logger.warning(f"Could not create /var/log/otel directory on update: {e}")

                #generate and update .env file
                #archive old .env
                old_env_path = os.path.join(self.config.base_path, instance_name, self.config.target_dir, ".env")
                ports = self.config.default_ports.copy()
                vault_password = ""
                sa_password = ""

                if os.path.exists(old_env_path):
                    archived_env_path = os.path.join(self.config.base_path, instance_name, self.config.target_dir, f".env_{safe_old_version}_{timestamp}")
                    shutil.copy2(old_env_path, archived_env_path)
                    self.logger.info(f"Archived old .env to: {archived_env_path}")

                    # get ports from old .env
                    with open(archived_env_path, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.startswith("HOST_MSSQL_PORT="):
                                ports["mssql_port"] = int(line.strip().split("=")[1])
                            elif line.startswith("HOST_APP_PORT="):
                                ports["app_port"] = int(line.strip().split("=")[1])
                            elif line.startswith("HOST_DATA_STAGING_PORT="):
                                ports["data_staging_port"] = int(line.strip().split("=")[1])
                            elif line.startswith("HOST_LOCAL_PORT="):
                                ports["local_port"] = int(line.strip().split("=")[1])
                            elif line.startswith("OTEL_HOST_GRPC_PORT="):
                                try:
                                    ports["otel_grpc_port"] = int(line.strip().split("=")[1])
                                except ValueError:
                                    pass
                            elif line.startswith("OTEL_JAEGER_CLIENT_PORT="):
                                try:
                                    ports["otel_jaeger_port"] = int(line.strip().split("=")[1])
                                except ValueError:
                                    pass
                            elif line.startswith("VAULT_PASSWORD="):
                                vault_password = line.strip().split("=", 1)[1]
                            elif line.startswith("HOST_MSSQL_PASSWORD="):
                                sa_password = line.strip().split("=", 1)[1]

                env_path = self.generate_env_file(
                    instance_name,
                    vault_password=vault_password,
                    sa_password=sa_password,
                    ports=ports,
                    overwrite_existing=True
                )
                self.logger.info(f"Updated .env file generated at: {env_path}")
                self.logger.info("HEAppE update initialization completed successfully")
                return {
                    "status": "success",
                    "appsettings": appsettings_new,
                    "instance_settings": get_instance_settings(instance_name)
                }
            except Exception as e:
                self.logger.error(f"Update initialization failed: {e}")
                raise e
