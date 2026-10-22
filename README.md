# HEAppE Management Admin Panel

Django web application for administration and management of HEAppE middleware.

---

QScheduler (quantum task scheduler) deployment and quantum machines: see [QScheduler_README.md](QScheduler_README.md).

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

### Tests and coverage report

Development tools (coverage.py) are in `requirements-dev.txt`, which also installs `requirements.txt`:

```bash
pip install -r requirements-dev.txt

python manage.py test heappe_ui                 # all tests
python manage.py qscheduler_coverage            # regenerate QScheduler_COVERAGE.md
python manage.py qscheduler_coverage --check    # fail if QScheduler_COVERAGE.md is out of date (CI)
```

[QScheduler_COVERAGE.md](QScheduler_COVERAGE.md) is generated: numbers and feature statuses are measured, the feature
descriptions come from `heappe_ui/reports/qscheduler_coverage.toml`. After changing QScheduler code or tests, update
that file (the report lists code not assigned to any feature), regenerate the report and commit it. The
`qscheduler-coverage` job in `.gitlab-ci.yml` runs the check on merge requests.

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

---

## Working with New HEAppE Core Versions & Unreleased REST APIs

When a new version of **HEAppE Core** is introduced (e.g., `v6.5.0` or newer) and the corresponding `py4heappe` Python client library has **not yet been released on PyPI**, you can automatically generate and use a local client SDK directly inside this project repository.

### Where and How to Place the Swagger Spec File

1. Obtain the updated Swagger / OpenAPI JSON specification file from HEAppE Core (for example, `RestApi-py4heappe.json` from the HEAppE Core build artifacts or repository).
2. Copy or place the JSON file into the **root directory** of this repository under one of the following filenames:
   - **`heappe_swagger.json`** (Recommended)
   - `swagger.json`

   *Example Command:*
   ```bash
   cp /path/to/heappe-core/SwaggerReference/RestApi-py4heappe.json heappe_swagger.json
   ```

### How Automatic SDK Generation Works (`heappe_generator.py`)

This project features an automated local SDK generator `heappe_generator.py`:

- **Automatic Check on Startup:**
  Whenever Django starts up or reloads, it checks for `heappe_swagger.json` in the root folder. If present and its content hash has changed, it automatically runs `heappe_generator.py` to regenerate the Python SDK into `py4heappe/heappe_v6/core/`.

- **Manual Trigger Command:**
  You can also trigger client generation manually at any time:
  ```bash
  python3 heappe_generator.py
  ```

- **Generation Strategy & Fallbacks:**
  1. **Method 1 (Local Codegen JAR):** Uses `swagger-codegen-cli-3.0.71.jar` with project templates in `codegen_templates/`.
  2. **Method 2 (Online Swagger Generator V3 API):** Sends spec to `https://generator3.swagger.io/api/generate` if local Java environment is missing or incompatible.
  3. **Method 3 (System OpenAPI Generator CLI):** Uses local `openapi-generator` CLI.

- **Local Package Override:**
  The generated code is stored in `py4heappe/heappe_v6/core/`. Python automatically loads this local package instead of any installed PyPI version, making all new REST API endpoints (such as `GET /heappe/JobManagement/ListDetailedJobsForAdmin`) immediately available in the application.

