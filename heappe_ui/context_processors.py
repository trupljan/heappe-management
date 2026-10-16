

import subprocess
import os
from heappe_ui.view.utils import clean_ver

def get_git_info():
    path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        version = subprocess.check_output(
            ['git', 'describe', '--tags', '--always', '--dirty'],
            cwd=path, stderr=subprocess.DEVNULL
        ).decode('utf-8').strip()
    except:
        version = "v0.0.0"

    try:
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=path, stderr=subprocess.DEVNULL
        ).decode('utf-8').strip()
    except:
        branch = "unknown"

    return {'version': version, 'branch': branch}


def git_version_renderer(request):
    info = get_git_info()
    return {
        'GIT_VERSION': info['version'],
        'GIT_BRANCH': info['branch']
    }


def get_instance_jaeger_url(instance_name):
    from heappe_ui.models import InstanceCredentials
    import os

    try:
        instance = InstanceCredentials.objects.filter(instance_name=instance_name).first()
    except Exception:
        instance = None

    if not instance:
        return "", 16686, True

    # Read .env to find OTEL_JAEGER_CLIENT_PORT and OTEL_DISABLED
    base_path = "/opt/heappe-deployment/"
    env_path = os.path.join(base_path, instance_name, "heappe-core", ".env")

    otel_jaeger_port = 16686
    otel_disabled = True

    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip()
                        if k == "OTEL_JAEGER_CLIENT_PORT":
                            try:
                                otel_jaeger_port = int(v)
                            except ValueError:
                                pass
                        elif k == "OTEL_DISABLED":
                            otel_disabled = (v.lower() == "true")
        except Exception as e:
            print(f"Error reading .env for Jaeger URL: {e}")

    # Extract host IP/domain only
    host = instance.heappe_host or "localhost"
    if "://" in host:
        host = host.split("://", 1)[1]
    if ":" in host:
        host = host.split(":", 1)[0]

    jaeger_url = f"http://{host}:{otel_jaeger_port}"
    return jaeger_url, otel_jaeger_port, otel_disabled


def middleware_update_renderer(request):
    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return {}

    path = request.path
    if any(p in path for p in ["/instances/", "/logout/", "/login/", "/reconnect/"]):
        return {}

    instance_name = request.session.get("chosen_instance")
    if not instance_name:
        return {}

    import time
    now = time.time()
    last_check = request.session.get("last_middleware_check_time", 0)
    last_checked_instance = request.session.get("last_middleware_checked_instance", "")

    # Retrieve cached values from session
    update_available = request.session.get("middleware_update_available", False)
    deployed_version = request.session.get("middleware_deployed_version", "")
    latest_version = request.session.get("middleware_latest_version", "")

    # Run check at most once per hour (3600 seconds), or if instance has changed, or if cache is empty.
    # Skip the check entirely if the instance failed to authenticate recently (within 60s) to prevent blocking on down services.
    should_run_check = (now - last_check > 3600) or (instance_name != last_checked_instance) or not deployed_version or not latest_version
    last_failed_auth = request.session.get("heappe_last_failed_auth", 0)
    if last_failed_auth and (now - last_failed_auth < 60):
        should_run_check = False

    if should_run_check:
        is_updating = False
        try:
            from heappe_ui.models import InstanceCredentials
            instance_service = InstanceCredentials.objects.filter(instance_name=instance_name).first()
            if instance_service:
                is_updating = getattr(instance_service, "is_updating", False)
            
            # 1. Try to query the Healthcheck endpoint
            import py4heappe.heappe_v6.core as hp
            if instance_service and not is_updating:
                try:
                    host = instance_service.heappe_host
                    port = instance_service.heappe_port
                    host_url = f"{host}:{port}"
                    if not host_url.startswith('http'):
                        host_url = 'http://' + host_url
                    
                    config = hp.Configuration()
                    config.host = host_url
                    config.verify_ssl = True
                    
                    api_client = hp.ApiClient(config)
                    # Patch the API client and associate with the request to apply consistent settings (like timeout)
                    from heappe_ui.auth_backend import patch_api_client
                    api_client._request = request
                    patch_api_client(api_client)

                    controller = hp.HealthApi(api_client)
                    health_info = controller.heappe_health_get(_request_timeout=3)
                    if health_info and health_info.version:
                        deployed_version = health_info.version.lstrip("vV")
                except Exception as e:
                    print(f"Healthcheck failed for context processor: {e}")

            # 2. Fallback to appsettings.json
            if not deployed_version:
                base_path = "/opt/heappe-deployment/"
                appsettings_path = os.path.join(base_path, instance_name, "app", "confs", "appsettings.json")
                if os.path.exists(appsettings_path):
                    try:
                        import json
                        with open(appsettings_path, "r", encoding="utf-8") as f:
                            appsettings_data = json.load(f)
                        deployed_version = appsettings_data.get("ApplicationAPISettings", {}).get("DeploymentSettings", {}).get("Version", "").lstrip("vV")
                    except Exception:
                        pass

            # 3. Fetch latest tags from git
            from heappe_ui.view.deploy import get_remote_tags
            repo_url = "https://github.com/It4innovations/HEAppE"
            branches = get_remote_tags(repo_url)
            if branches:
                latest_version = branches[0].lstrip("vV")
                

                try:
                    if clean_ver(latest_version) > clean_ver(deployed_version):
                        update_available = True
                    else:
                        update_available = False
                except Exception:
                    if latest_version.lower().lstrip('v') != deployed_version.lower().lstrip('v'):
                        update_available = True
                    else:
                        update_available = False

        except Exception as e:
            print(f"Error checking middleware update: {e}")

        request.session["last_middleware_check_time"] = 0 if is_updating else now
        request.session["last_middleware_checked_instance"] = instance_name
        request.session["middleware_update_available"] = update_available
        request.session["middleware_deployed_version"] = deployed_version
        request.session["middleware_latest_version"] = latest_version

    # Cache status check
    from django.conf import settings
    timestamp_file = os.path.join(settings.BASE_DIR, "metadata_last_modified.txt")
    last_global_mod = 0.0
    if os.path.exists(timestamp_file):
        try:
            with open(timestamp_file, "r") as f:
                last_global_mod = float(f.read().strip())
        except Exception:
            pass

    cache_keys = {
        "clusters_cache": "Clusters",
        "node_types_cache": "Queues",
        "all_adaptor_users_cache": "Users",
        "accountings_cache": "Accountings",
        "queue_groups_cache": "Queue Groups",
        "mappings_cache": "Mappings",
        "projects_list_cache": "Projects"
    }

    # Add project templates cache dynamically if on a project detail page and it exists in session
    parts = request.path.strip('/').split('/')
    if len(parts) >= 2:
        if parts[0] == 'projects' and parts[1].isdigit():
            p_id = parts[1]
            key = f"command_templates_cache_{p_id}"
            if request.session.get(f"{key}_time") is not None:
                cache_keys[key] = "Templates"
        elif parts[0] == 'command-templates' and parts[1].isdigit():
            t_id = parts[1]
            key = f"command_template_detail_cache_{t_id}"
            if request.session.get(f"{key}_time") is not None:
                cache_keys[key] = "Template Detail"

    cache_status = {}
    disable_cache = getattr(settings, 'DISABLE_CACHE', False)
    if not disable_cache:
        for key, label in cache_keys.items():
            cache_time = request.session.get(f"{key}_time")
            try:
                cache_time_float = float(cache_time) if cache_time is not None else None
            except (TypeError, ValueError):
                cache_time_float = None

            if cache_time_float is not None and cache_time_float >= last_global_mod:
                age = int(now - cache_time_float)
                remaining = max(0, 300 - age)
                if remaining > 0:
                    cache_status[label] = {
                        'is_live': False,
                        'remaining': remaining,
                        'age_str': f"{age}s" if age < 60 else f"{age // 60}m {age % 60}s"
                    }
                else:
                    cache_status[label] = {
                        'is_live': True,
                        'remaining': 0,
                        'age_str': "Live"
                    }
            else:
                cache_status[label] = {
                    'is_live': True,
                    'remaining': 0,
                    'age_str': "Live"
                }

    # Fetch API and Swagger URLs for the selected instance
    api_links = {}
    jaeger_url = ""
    jaeger_port = 16686
    otel_disabled = True
    otel_active = False

    if instance_name:
        try:
            from heappe_ui.view.utils import get_instance_api_links
            api_links = get_instance_api_links(instance_name)
        except Exception as e:
            print(f"Error getting instance API links: {e}")

        try:
            jaeger_url, jaeger_port, otel_disabled = get_instance_jaeger_url(instance_name)
            if not otel_disabled:
                import docker
                client = docker.from_env()
                # Check if otel-collector is running
                for c in client.containers.list(all=False):
                    if c.labels.get('com.docker.compose.project') == instance_name:
                        service_name = c.labels.get('com.docker.compose.service', '')
                        if 'otel-collector' in service_name or 'otel-collector' in c.name:
                            otel_active = True
                            break
        except Exception as e:
            print(f"Error in context processor telemetry check: {e}")

    is_v6_4_0_plus = False
    is_v6_5_0_plus = False
    if deployed_version:
        is_v6_4_0_plus = (clean_ver(deployed_version) >= [6, 4, 0])
        is_v6_5_0_plus = (clean_ver(deployed_version) >= [6, 5, 0])

    last_failed_auth = request.session.get("heappe_last_failed_auth", 0)
    cooldown_remaining = 0
    if last_failed_auth:
        import time
        elapsed = time.time() - last_failed_auth
        if elapsed < 30:
            cooldown_remaining = max(1, int(30 - elapsed))

    return {
        'caching_enabled': not disable_cache,
        'middleware_update_available': update_available,
        'middleware_deployed_version': deployed_version,
        'middleware_latest_version': latest_version,
        'cache_status': cache_status,
        'is_v6_4_0_plus': is_v6_4_0_plus,
        'is_v6_5_0_plus': is_v6_5_0_plus,
        'jaeger_url': jaeger_url,
        'jaeger_port': jaeger_port,
        'otel_disabled': otel_disabled,
        'otel_active': otel_active,
        'heappe_session_code': request.session.get('heappe_session_code', ''),
        'heappe_api_key': request.session.get('heappe_api_key_header', '') or request.session.get('heappe_api_key', ''),
        'heappe_host': request.session.get('heappe_host', ''),
        'cooldown_remaining': cooldown_remaining,
        **api_links
    }