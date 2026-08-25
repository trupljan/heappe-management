# HEAppE Management Admin Panel

Django web application for administration and management of HEAppE middleware.

---

## Quickstart (Local Development)

### Requirements
- **Python 3.12** (Recommended, min. Python 3.10+)

### Commands for running in terminal

```bash
# 1. Navigate to the project directory
cd /path/to/heappe-management

# 2. Create virtual environment (if not created yet)
python3 -m venv .venv

# 3. Activate virtual environment
# Linux / macOS:
source .venv/bin/activate
# Windows (CMD):
# .venv\Scripts\activate.bat
# Windows (PowerShell):
# .venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install -r requirements.txt

# 5. Run database migrations
python manage.py migrate

# 6. Start development server
python manage.py runserver
```

The application will be accessible at:
- **Web App:** [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Django Admin:** [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

---

## Running in PyCharm

### 1. Configure Python Interpreter
1. Open **Settings -> Project: heappe-management -> Python Interpreter** in PyCharm.
2. Select the existing virtual environment in `.venv` (`.venv/bin/python`).

### 2. Run Configuration
- **PyCharm Professional:** Go to **Settings -> Languages & Frameworks -> Django**, check *Enable Django Support*, set Root to project folder and Settings to `adminpanel/settings.py`. Then run the automatically generated **Django Server** configuration.
- **PyCharm Community:** Go to **Edit Configurations...**, add a new **Python** configuration:
  - **Script path:** `manage.py`
  - **Parameters:** `runserver`
  - **Working directory:** project directory

---

## Server Deployment

For deploying on a production or test Linux server, use the included deployment script `deploy.sh`:

```bash
# Deploy default branch (main)
./deploy.sh

# Deploy specific branch or tag
GIT_TAG=v1.0.0 ./deploy.sh
```

The script automatically fetches changes from Git, updates dependencies, runs migrations, collects static files, and restarts the `adminpanel` systemd service.
