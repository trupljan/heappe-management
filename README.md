# HEAppE Management

Django-based admin panel for HEAppE middleware management. Provides a web interface for deploying HEAppE containers and managing HEAppE API endpoints

## Local Development

### Prerequisites

- Recommended [uv](https://docs.astral.sh/uv/) Python package manager
- Python 3.12 virtual env
- System ODBC library (`unixodbc` on Arch, `unixodbc-dev` on Debian/Ubuntu).

### Quickstart

```bash
# 1. Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Sync dependencies (creates .venv with Python 3.12)
uv sync

# 2.5 Use local py4heappe for future release
# Change your local path
uv pip install -e ~/<change_this>/Py4HEAppE

# 3. Run database migrations
uv run python manage.py migrate

# 4. Create admin user for first time login
uv run python manage.py shell -c "from django.contrib.auth import get_user_model; User=get_user_model(); User.objects.filter(username='admin').exists() or User.objects.create_superuser('admin', 'admin@example.com', 'admin')"

# 5. Setup access to /opt
sudo mkdir /opt/heappe-deployment
sudo chown -R $USER:$USER /opt/heappe-deployment

# 6. Run development server
uv run python manage.py runserver 0.0.0.0:8000

# Or run with gunicorn (production-like)
uv run gunicorn --bind 0.0.0.0:8000 adminpanel.wsgi:application --workers 1
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `IS_DEV` | Enable debug mode | `False` |
| `MANAGEMENT_PROXYPASS` | Mount app under `/management` prefix | `False` |

## Production Deployment (Ansible)

The Ansible playbooks handle full server setup: Python 3.12 from source, Docker, Nginx, systemd service, and firewall configuration.

### Prerequisites

- Target server: Ubuntu/Debian or CentOS/RHEL
- Ansible installed locally
- SSH access to target server

### Quickstart

```bash
# 1. Configure inventory
cd ansible-deployment
# Edit inventory.ini with your target server(s)

# 2. Edit playbook variables (nginx domain, SSL, etc.)
# playbook_deploy_heappemanagement.yml -> vars section

# 3. Run deployment
ansible-playbook -i inventory.ini --user <your_user> --ask-pass --ask-become-pass playbook_deploy_heappemanagement.yml
```

Default admin credentials are auto-created on first deploy:
- Username: `admin`
- Password: `admin`

**Change these immediately in production!**
