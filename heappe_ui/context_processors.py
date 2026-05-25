

import subprocess
import os

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


def middleware_update_renderer(request):
    if not request.user.is_authenticated:
        return {}

    instance_name = request.session.get("chosen_instance")
    if not instance_name:
        return {}

    import time
    now = time.time()
    last_check = request.session.get("last_middleware_check_time", 0)

    # Cache check result for 15 minutes (900 seconds)
    if now - last_check < 900 and "middleware_update_available" in request.session:
        return {
            'middleware_update_available': request.session.get("middleware_update_available"),
            'middleware_deployed_version': request.session.get("middleware_deployed_version"),
            'middleware_latest_version': request.session.get("middleware_latest_version"),
        }

    deployed_version = ""
    latest_version = ""
    update_available = False

    try:
        from heappe_ui.models import InstanceCredentials
        instance_service = InstanceCredentials.objects.filter(instance_name=instance_name).first()
        
        # 1. Try to query the Healthcheck endpoint
        import py4heappe.heappe_v6.core as hp
        if instance_service:
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
                controller = hp.HealthApi(api_client)
                health_info = controller.heappe_health_get()
                if health_info and health_info.version:
                    deployed_version = health_info.version.lstrip("vV")
            except Exception as e:
                print(f"Healthcheck failed for context processor: {e}")

        # 2. Fallback to appsettings.json
        if not deployed_version:
            base_path = "/opt/heappe-deployment/"
            import os
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
            
            def clean_ver(v):
                return [int(n) for n in v.lower().lstrip('v').split('.') if n.isdigit()]
            
            try:
                if clean_ver(latest_version) > clean_ver(deployed_version):
                    update_available = True
            except Exception:
                if latest_version.lower().lstrip('v') != deployed_version.lower().lstrip('v'):
                    update_available = True

    except Exception as e:
        print(f"Error checking middleware update: {e}")

    request.session["last_middleware_check_time"] = now
    request.session["middleware_update_available"] = update_available
    request.session["middleware_deployed_version"] = deployed_version
    request.session["middleware_latest_version"] = latest_version

    return {
        'middleware_update_available': update_available,
        'middleware_deployed_version': deployed_version,
        'middleware_latest_version': latest_version,
    }