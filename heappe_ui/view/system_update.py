import json
import subprocess
import os
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render
from django.conf import settings
from heappe_ui.view.imports import *

DEPLOY_SCRIPT_NAME = "deploy.sh"
DEPLOY_SCRIPT_PATH = os.path.join(settings.BASE_DIR, DEPLOY_SCRIPT_NAME)

@login_required
def update_app(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'message': 'Invalid JSON'}, status=400)

        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return JsonResponse({'message': 'Username and password are required'}, status=401)

        try:
            # Path to the repository (e.g., project root directory)
            repo_path = settings.BASE_DIR

            # Get the current Git remote URL
            result = subprocess.run(
                ['git', 'remote', 'get-url', 'origin'],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            remote_url = result.stdout.strip()

            # Modify the remote URL to include credentials for HTTPS
            if remote_url.startswith('https://'):
                # Insert credentials into the URL (e.g., https://username:password@domain.com/...)
                remote_url_parts = remote_url.split('https://')
                auth_remote_url = f'https://{username}:{password}@{remote_url_parts[1]}'
            else:
                return JsonResponse({'message': 'Git remote is not HTTPS'}, status=400)

            # Commands for the update
            commands = [
                ['git', 'pull', auth_remote_url],  # Pull with authenticated URL
                ['pip', 'install', '-r', 'requirements.txt'],  # Updates dependencies
                ['python3', 'manage.py', 'migrate'],  # Runs database migrations
            ]

            # Execute commands
            for cmd in commands:
                result = subprocess.run(
                    cmd,
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    check=True
                )
                if result.returncode != 0:
                    return JsonResponse({'message': f'Error during {cmd}: {result.stderr}'}, status=500)

            # Optional: Restart the server
            # Note: This depends on your deployment (e.g., Gunicorn, uWSGI).
            touch_file = os.path.join(repo_path, 'reload.trigger')
            with open(touch_file, 'a'):
                os.utime(touch_file, None)

            return JsonResponse({'message': 'Application updated successfully!'})

        except subprocess.CalledProcessError as e:
            return JsonResponse({'message': f'Update error: {e.stderr}'}, status=500)
        except Exception as e:
            return JsonResponse({'message': f'Unexpected error: {str(e)}'}, status=500)

    return render(request, "update_app.html")

def check_for_updates(request):
    repo_path = settings.BASE_DIR
    try:
        subprocess.run(['git', 'fetch', '--all'], cwd=repo_path, check=True, timeout=15, capture_output=True)

        local_hash = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_path).decode().strip()
        branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=repo_path).decode().strip()
        remote_hash = subprocess.check_output(['git', 'rev-parse', '@{u}'], cwd=repo_path).decode().strip()

        update_available = local_hash != remote_hash
        commit_messages = []

        if update_available:
            log_output = subprocess.check_output(
                ['git', 'log', 'HEAD..@{u}', '--format=%s'],
                cwd=repo_path
            ).decode().strip()

            if log_output:
                commit_messages = log_output.split('\n')

        return JsonResponse({
            'update_available': update_available,
            'local': local_hash[:7],
            'remote': remote_hash[:7],
            'branch': branch,
            'changes': commit_messages
        })


    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        return JsonResponse({'error': f'Git error: {error_msg}'}, status=500)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def update_server_page(request):
    """Renders the page with the update button and form."""
    return render(request, 'update_server.html')

def execute_git_ls_remote(git_url, git_username=None, git_password=None):
    """
    Executes 'git ls-remote' to get branches and tags, handling credentials.
    Returns (list_of_refs, error_message, status_code).
    """

    # 1. Prepare Git URL with credentials for HTTPS access
    if git_username and git_password:
        url_parts = git_url.split('://', 1)
        if len(url_parts) == 2:
            # Format: https://<username>:<password>@<domain>/<repo.git>
            domain_and_path = url_parts[1]
            auth_url = f"{url_parts[0]}://{git_username}:{git_password}@{domain_and_path}"
        else:
            # Nevalidní URL formát, použijeme původní
            auth_url = git_url
    else:
        auth_url = git_url

    # 2. Prepare the command: list all branches (--heads) and tags (--tags)
    command = ['git', 'ls-remote', '--heads', '--tags', auth_url]

    try:
        # Použijeme nastavení ověřování SSL z prostředí Git (je-li potřeba)
        # Tímto se zamezí chybám SSL, pokud není certifikát známý
        env = os.environ.copy()
        # env['GIT_SSL_NO_VERIFY'] = 'true' # Povolte pouze v testovacím prostředí

        result = subprocess.run(command,
                                capture_output=True,
                                text=True,
                                check=False,
                                timeout=15,
                                env=env) # Předáme upravené prostředí

        # 3. Handle Git errors
        if result.returncode != 0:
            error_output = result.stderr.lower()

            # Authentication failure check
            if any(auth_error in error_output for auth_error in
                   ['authentication failed', '401 unauthorized', '403 forbidden', 'credential', 'could not read username']):
                return None, "Authentication required or failed for Git URL. Status code: 401.", 401

            return None, f"Git error: {result.stderr.strip()}", 500

        # 4. Parse the successful output
        refs = []
        for line in result.stdout.splitlines():
            if '\t' in line:
                ref = line.split('\t')[1]

                # Clean up: strip 'refs/heads/' or 'refs/tags/' prefix
                if ref.startswith('refs/heads/'):
                    refs.append(ref.replace('refs/heads/', ''))
                elif ref.startswith('refs/tags/'):
                    # Ignore the dereferenced tag lines (e.g., 'v1.0.0^{}')
                    if not ref.endswith('^{}'):
                        refs.append(ref.replace('refs/tags/', ''))

        # Return unique and sorted refs (e.g., ['main', 'v1.0.0'])
        return sorted(list(set(refs))), None, 200

    except subprocess.TimeoutExpired:
        return None, "Git operation timed out (15s).", 504
    except Exception as e:
        return None, f"Internal server error during Git check: {e}", 500

@csrf_exempt
@require_http_methods(["POST"])
# Použití @csrf_exempt je zde v pořádku, protože na backendu dojde k ověření přes GIT,
# ale v produkci zvažte přidání např. @login_required + @ensure_csrf_cookie nebo jiný token pro AJAX.
# Pokud je tento endpoint volán jen po úspěšném přihlášení, je to mírně bezpečnější.
def check_repo_and_fetch_branches(request):
    """API endpoint to check a Git URL and fetch available branches/tags."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON.")

    git_url = data.get('git_url')
    git_username = data.get('git_username')
    # Opatrně s heslem - zde ho přijímáme a rovnou posíláme do helper funkce, kde je použito v URL
    git_password = data.get('git_password')

    if not git_url:
        return JsonResponse({'message': 'Git URL is required.'}, status=400)

    # Volání helper funkce, která provede Git operaci
    tags_and_branches, error_message, status_code = execute_git_ls_remote(
        git_url, git_username, git_password
    )

    if tags_and_branches:
        return JsonResponse({
            'status': 'success',
            'message': 'Repository check successful.',
            'git_url': git_url,
            'tags_and_branches': tags_and_branches
        }, status=status_code)
    else:
        # Authentication failure (401) or general error (500)
        return JsonResponse({
            'status': 'error',
            'message': error_message,
            'git_url': git_url,
        }, status=status_code)

@require_http_methods(["POST"])
@login_required # Důležité: Tuto kritickou operaci smí spustit jen přihlášený uživatel.
def trigger_deployment_direct(request):
    """Final API endpoint to execute the deployment script."""
    # 1. Input Validation and Parsing
    try:
        # Použijeme .decode('utf-8') pro jistotu
        data = json.loads(request.body.decode('utf-8'))
        git_url = data.get('git_url')
        git_tag = data.get('git_tag')
        git_user = data.get('git_username', '')
        git_pass = data.get('git_password', '')

        if not all([git_url, git_tag]):
            return JsonResponse({"status": "error", "message": "Missing Git URL or selected Tag/Branch."}, status=400)

    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON request body."}, status=400)

    # 2. Check for Script and Permissions
    if not os.path.exists(DEPLOY_SCRIPT_PATH):
        return JsonResponse({"status": "error", "message": f"Deployment script not found at {DEPLOY_SCRIPT_PATH}"},
                            status=500)
    try:
        # Ensure script is executable (rwx pro vlastníka, r-- pro skupinu/ostatní)
        os.chmod(DEPLOY_SCRIPT_PATH, 0o744)
    except Exception as e:
        return JsonResponse({"status": "error", "message": f"Error setting permissions on script: {e}"}, status=500)

    # 3. Launch Subprocess with Environment Variables
    try:
        env_vars = os.environ.copy()

        # Pass the dynamic inputs as environment variables
        env_vars['GIT_URL'] = git_url
        env_vars['GIT_TAG'] = git_tag
        env_vars['GIT_USER'] = git_user
        env_vars['GIT_PASS'] = git_pass  # SENSITIVE!

        # Doporučené: Použít shlex pro správné formátování příkazu
        # Ale jelikož je spouštěn jen skript, stačí i tento zápis
        process = subprocess.Popen(
            ['/bin/bash', DEPLOY_SCRIPT_PATH],
            cwd=settings.BASE_DIR,
            start_new_session=True,  # Důležité: Proces se odpojí a běží nezávisle (daemonizace)
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env_vars
        )

        return JsonResponse({
            "status": "success",
            "message": f"Deployment script ({DEPLOY_SCRIPT_NAME}) launched on background process {process.pid}. Server will restart shortly.",
            "git_tag": git_tag,
            "git_url": git_url
        })

    except Exception as e:
        return JsonResponse({"status": "error", "message": f"Fatal error launching script: {e}"}, status=500)

@login_required
def heappe_check_api(request, min_version):
    try:
        controller = hp.HealthApi(request.api_instance)
        health_info = controller.heappe_health_get()
        current_version = health_info.version.lstrip("vV")

        is_ok = current_version >= min_version

        return JsonResponse({
            "status": "success" if is_ok else "version_mismatch",
            "current_version": current_version,
            "required_version": min_version,
            "message": "OK" if is_ok else f"Version {current_version} is less than required {min_version} for that feature."
        })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

