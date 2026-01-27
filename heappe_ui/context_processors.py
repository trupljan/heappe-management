

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