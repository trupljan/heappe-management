from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
import json

@login_required
def interactive_docs_view(request: HttpRequest) -> HttpResponse:
    """
    Renders the interactive help and documentation system.
    Provides structured English documentation for every single page in the HEAppE Management UI.
    """
    docs_data = [
        {
            "id": "dashboard",
            "category": "Main Panel",
            "title": "Dashboard",
            "route": "/",
            "icon": "bi-house-door",
            "description": "The central landing page of the HEAppE Management Admin Panel. It serves as a real-time monitor for the overall health of the selected HEAppE middleware instance and aggregates cluster, project, queue, and job statistics.",
            "why_exists": "To give administrators an immediate, high-level operational overview. Instead of searching through server logs or calling multiple APIs manually, the dashboard aggregates health checks, deployment updates, and active job counters in one place.",
            "api_endpoints": [
                {"name": "heappe_health_get", "description": "Fetches health status of the middleware instance."},
                {"name": "heappe_management_version_information_get", "description": "Obtains API version and environment details."},
                {"name": "heappe_management_clusters_get", "description": "Loads clusters count and summary."},
                {"name": "heappe_management_projects_get", "description": "Loads projects count and summary."},
                {"name": "heappe_job_reporting_jobs_state_agregation_report_get", "description": "Aggregates job counts by execution states."},
                {"name": "heappe_job_reporting_jobs_detailed_report_get", "description": "Retrieves the list of jobs within the selected reporting timeframe."}
            ],
            "walkthrough": [
                "Verify the connection status using the top right status badge and the health section.",
                "Review the color-coded circular statistics representing jobs (Queued, Running, Finished, Failed).",
                "Filter the detailed job history table by selecting a date range (capped at 90 days for performance).",
                "Look out for the update notification banner if a newer HEAppE middleware release is available on GitHub."
            ],
            "ui_elements": [
                {"selector": ".health-card", "label": "Middleware Health", "explanation": "Displays check results for database connection, cluster communication, and service health."},
                {"selector": ".job-chart", "label": "State Aggregation Chart", "explanation": "A visual breakdown of jobs. Hovering displays exact counts for states like WaitingForServiceAccount or Canceled."},
                {"selector": ".job-table", "label": "Paged Jobs Seach", "explanation": "A tabular list of recent jobs with pagination, sorting, and inline links to check individual job status."}
            ]
        },
        {
            "id": "projects",
            "category": "Projects & Jobs",
            "title": "Projects Management",
            "route": "/projects/",
            "icon": "bi-folder",
            "description": "Projects are the primary organizational units in HEAppE. Every job submission, user access limit, and cluster filesystem path allocation must be tied to a specific project.",
            "why_exists": "HPC systems enforce strict multi-tenancy and resource accounting. Projects group users, limit compute hours on partitions, and configure sandbox paths (scratch, permanent, and project folders) on target clusters.",
            "api_endpoints": [
                {"name": "heappe_management_projects_get", "description": "Retrieves all projects."},
                {"name": "heappe_management_project_get", "description": "Fetches details of a single project by ID."},
                {"name": "heappe_management_project_post", "description": "Creates a new project."},
                {"name": "heappe_management_project_put", "description": "Updates project name, description, or validity dates."}
            ],
            "walkthrough": [
                "Navigate to the Projects list to view all active, expired, or pending projects.",
                "Click 'New Project' to register a project, defining its name, description, and validity range.",
                "Select a project to view its detailed view, showing command templates, assigned clusters, and active accounts."
            ],
            "ui_elements": [
                {"selector": ".btn-assign-cluster", "label": "Assign to Cluster", "explanation": "Binds this project to an HPC cluster and defines the storage directory structure."},
                {"selector": "#hpc-accounts-tab", "label": "HPC Accounts Tab", "explanation": "Manages user credentials and SSH authentication keys for cluster access."}
            ]
        },
        {
            "id": "hpc_accounts",
            "category": "Projects & Jobs",
            "title": "HPC Accounts & Verification",
            "route": "/projects/<id>/#hpc-accounts",
            "icon": "bi-shield-check",
            "description": "Manages individual HPC account links and credentials used by the HEAppE middleware to authenticate on the target clusters. This is where SSH keys are generated and validated.",
            "why_exists": "Instead of using a single global service account, HEAppE can map actions to individual cluster accounts. This section ensures the authentication keys are initialized, valid, and successfully authorized on the HPC main node.",
            "api_endpoints": [
                {"name": "heappe_management_test_cluster_authentication_credential_hpc_access_post", "description": "Tests if HEAppE can log in and write to directories on the cluster using the account's credentials."},
                {"name": "heappe_management_initialize_hpc_account_post", "description": "Initializes directory structure and credentials for the HPC account."},
                {"name": "heappe_management_regenerate_ssh_key_post", "description": "Regenerates SSH keypairs and outputs the public key for cluster authorization."}
            ],
            "walkthrough": [
                "Within a Project, go to the HPC Accounts card.",
                "Click 'Test HPC Access' to verify if the middleware can successfully establish an SSH handshake and write test files.",
                "Click 'Regenerate SSH Key' if credentials have expired, then copy the generated public key to the cluster's `.ssh/authorized_keys` file.",
                "Click 'Initialize Account' to let the middleware prepare directory hierarchies on the cluster."
            ],
            "ui_elements": [
                {"selector": ".btn-test-auth", "label": "Test Auth Connection", "explanation": "Triggers a live SSH connection check. Displays a green success banner or a detailed error traceback if it fails."},
                {"selector": ".ssh-key-display", "label": "Public Key display box", "explanation": "A copyable textarea displaying the RSA/ECDSA public key to be added to the HPC cluster."}
            ]
        },
        {
            "id": "test_jobs",
            "category": "Projects & Jobs",
            "title": "Test Job Submission",
            "route": "/submit-test-job/<command_template_id>",
            "icon": "bi-play-fill",
            "description": "Enables administrators to manually submit a test job to an HPC cluster based on a chosen command template. It includes configuration parameter entry and real-time output monitoring.",
            "why_exists": "Verifying that the integration of the middleware, scheduler, user accounts, and filesystem storage works correctly is difficult without submitting actual work. This view allows sandbox testing to ensure end-to-end functionality.",
            "api_endpoints": [
                {"name": "heappe_job_management_submit_job_post", "description": "Submits a job configuration to the cluster planning queue."},
                {"name": "heappe_job_reporting_job_status_get", "description": "Queries the current execution state of the submitted test job."},
                {"name": "heappe_job_reporting_job_file_download_get", "description": "Downloads output files or logs from the cluster storage."}
            ],
            "walkthrough": [
                "Select a Command Template and click 'Submit Test Job'.",
                "Fill in template arguments, environment parameters, and resource limits (cores, nodes).",
                "Submit the job and monitor the progress. The page redirects to the status viewer.",
                "View the live output logs as they stream from the cluster and download result files upon completion."
            ],
            "ui_elements": [
                {"selector": "#submit-job-form", "label": "Job Parameter Form", "explanation": "Dynamically builds form fields based on variables defined in the selected Command Template."},
                {"selector": ".log-streamer-box", "label": "Live Console Output", "explanation": "An interactive terminal emulator showing stdout/stderr log output directly from the executing HPC process."}
            ]
        },
        {
            "id": "clusters",
            "category": "Infrastructure",
            "title": "Clusters Configuration",
            "route": "/clusters/",
            "icon": "bi-server",
            "description": "Configure the High-Performance Computing (HPC) environments managed by HEAppE. This includes setting hostnames, ports, scheduler types (Slurm, PBS, FirecREST), and communication protocols.",
            "why_exists": "Each HPC cluster has different configurations, scheduler APIs, and network constraints. This section provides a unified layout to register clusters, configure network routing, and deploy simulators for local testing.",
            "api_endpoints": [
                {"name": "heappe_management_clusters_get", "description": "Fetches all cluster details."},
                {"name": "heappe_management_cluster_post", "description": "Registers a new cluster configuration."},
                {"name": "heappe_management_cluster_put", "description": "Updates an existing cluster configurations."},
                {"name": "heappe_management_cluster_delete", "description": "Deletes a cluster configuration."}
            ],
            "walkthrough": [
                "Click 'Create Cluster' to register a new machine. Choose a name and Master Node hostname.",
                "Select a Scheduler (e.g. Slurm) and a Connection Protocol (e.g., SSH).",
                "For HEAppE 6.4.0+, define custom JSON configurations in the Custom Configuration area if using FirecREST or Expirio.",
                "Link a proxy connection under the 'Proxy connections' tab if the cluster is located in an isolated private network."
            ],
            "ui_elements": [
                {"selector": "#tab-filetransfer", "label": "File Transfer Methods Tab", "explanation": "Configures SFTP/SCP server connections used by HEAppE to push input data and retrieve job results."},
                {"selector": ".btn-setup-slurm", "label": "Slurm Simulator Setup", "explanation": "Starts a background process that spawns a Docker container containing a Slurm simulator, making it easy to test job execution locally."}
            ]
        },
        {
            "id": "queues",
            "category": "Infrastructure",
            "title": "Queues (Node Types)",
            "route": "/queues/",
            "icon": "bi-list-columns-reverse",
            "description": "Manages Cluster Node Types, which correspond to partition queues on the HPC cluster. It defines hardware attributes, core counts, memory size, and limits for each queue.",
            "why_exists": "HPC schedulers partition clusters into queues (e.g., fast CPU, high-memory, GPU). HEAppE needs to understand these partitions, their constraints, and file transfer protocols to route user tasks to appropriate hardware resources.",
            "api_endpoints": [
                {"name": "heappe_management_cluster_node_types_get", "description": "Retrieves the list of all registered node types / queues."},
                {"name": "heappe_management_cluster_node_type_post", "description": "Creates a new queue definition on a cluster."},
                {"name": "heappe_management_cluster_node_type_put", "description": "Modifies limits or specifications of a queue."},
                {"name": "heappe_management_cluster_node_type_delete", "description": "Deletes a queue definition."}
            ],
            "walkthrough": [
                "Go to Queues to see the complete list of partitions across all clusters.",
                "Create a new queue by specifying core limits, memory limitations, and the linked file transfer protocol.",
                "Double-check that the partition name matches the configuration of the scheduler on the actual cluster."
            ],
            "ui_elements": [
                {"selector": ".table-queues", "label": "Queues Table", "explanation": "Lists queue partition names, node counts, and linked clusters. Includes inline edit buttons."}
            ]
        },
        {
            "id": "queue_groups",
            "category": "Infrastructure",
            "title": "Queue Groups (Aggregations)",
            "route": "/queue-groups/",
            "icon": "bi-tags",
            "description": "Groups multiple queues (partitions) into single entities for resource allocation, pricing formulas, and usage accounting.",
            "why_exists": "Instead of allocating computing budgets per individual partition, administrators can aggregate multiple nodes or queues into a 'Queue Group'. This group can have pricing formulas and shared budget quotas for projects.",
            "api_endpoints": [
                {"name": "heappe_management_cluster_node_type_aggregations_get", "description": "Fetches all queue groups."},
                {"name": "heappe_management_cluster_node_type_aggregation_post", "description": "Creates a new queue group (aggregation)."},
                {"name": "heappe_management_cluster_node_type_aggregation_put", "description": "Modifies queue group attributes."},
                {"name": "heappe_management_cluster_node_type_aggregation_delete", "description": "Deletes a queue group."}
            ],
            "walkthrough": [
                "Go to Queue Groups and click 'New Queue Group'.",
                "Define a name and set validity dates for the group.",
                "Assign node types (queues) to the group from the details page.",
                "Configure price calculation formulas (e.g. NodeHour cost rates) and assign them to the group."
            ],
            "ui_elements": [
                {"selector": ".btn-assign-formula", "label": "Assign Formula", "explanation": "Binds a charging formula to calculate compute credit consumption on this group's queues."}
            ]
        },
        {
            "id": "command_templates",
            "category": "Projects & Jobs",
            "title": "Command Templates",
            "route": "/command-templates/<project_id>/new/",
            "icon": "bi-terminal",
            "description": "Templates defining standardized commands, script calls, arguments, environment configurations, and parameters for running applications on clusters.",
            "why_exists": "Users shouldn't have to write raw shell scripts to submit jobs. Command templates allow administrators to define pre-configured application scripts (e.g. running OpenFOAM, TensorFlow). Users only supply variable parameters.",
            "api_endpoints": [
                {"name": "heappe_management_command_templates_get", "description": "Fetches all command templates."},
                {"name": "heappe_management_command_template_post", "description": "Registers a new command template."},
                {"name": "heappe_management_command_template_put", "description": "Updates template configuration."},
                {"name": "heappe_management_command_template_parameter_post", "description": "Adds a configurable parameter variable to the template."}
            ],
            "walkthrough": [
                "Under a project, create a Command Template.",
                "Define the Executable File name and the execution script command line template.",
                "Add parameters (variables) indicating if they are required, have defaults, or are mapped as environment variables.",
                "Submit a test job based on the template to verify correct parameter interpolation."
            ],
            "ui_elements": [
                {"selector": ".parameters-list", "label": "Template Parameters", "explanation": "Interactive list of command arguments. Supports sorting, adding defaults, and input validations."}
            ]
        },
        {
            "id": "accounting",
            "category": "Accounting",
            "title": "Accounting & Resource Limits",
            "route": "/accounting/<project_id>",
            "icon": "bi-wallet2",
            "description": "Manages alocation limits, credit tracking, and validity ranges of compute resources assigned to projects.",
            "why_exists": "Compute time on clusters is expensive. This page allows administrators to assign a specific 'Queue Group' budget to a project, granting compute hour credits and tracking active resource utilization.",
            "api_endpoints": [
                {"name": "heappe_management_accountings_get", "description": "Fetches accounting records."},
                {"name": "heappe_management_project_cluster_node_type_aggregations_get", "description": "Fetches node group allocations assigned to a project."},
                {"name": "heappe_management_project_cluster_node_type_aggregation_post", "description": "Binds a queue group budget allocation to a project."}
            ],
            "walkthrough": [
                "Go to the Accounting page of a specific project.",
                "Click 'Assign Queue Group' to link a compute budget.",
                "Enter the allocated compute limit (e.g., Node Hours).",
                "Observe the active accounting records representing actual consumption levels."
            ],
            "ui_elements": [
                {"selector": ".allocation-total", "label": "Total Allocation Summary", "explanation": "Aggregates total node hour allocations across all linked queue groups for the project."}
            ]
        },
        {
            "id": "user_management",
            "category": "User Management",
            "title": "User Management (Adaptor Users)",
            "route": "/manage-external-users/",
            "icon": "bi-people",
            "description": "Create and manage Adaptor Users, who represent external researchers or API clients authorized to submit jobs to HEAppE.",
            "why_exists": "Separates the administrative interface from the API usage layers. Adaptor users are clients who authenticate against HEAppE to consume compute time. Here you manage their credentials and assign their project permissions.",
            "api_endpoints": [
                {"name": "heappe_management_adaptor_users_get", "description": "Fetches all external adaptor users."},
                {"name": "heappe_management_adaptor_user_post", "description": "Registers a new adaptor user."},
                {"name": "heappe_management_assign_adaptor_user_to_project_post", "description": "Grants an adaptor user permission to access a project under a specific role (Admin, User, Auditor)."}
            ],
            "walkthrough": [
                "Go to User Management to list all registered external users.",
                "Click 'Create User' to add an account with password credentials.",
                "Select a Project and associate the user with a role (e.g., Standard User) to allow them to submit tasks."
            ],
            "ui_elements": [
                {"selector": ".role-badge", "label": "Project Roles", "explanation": "Indicates user clearance: Project Administrators can edit settings; Users submit tasks; Auditors only view logs."}
            ]
        },
        {
            "id": "containers",
            "category": "HEAppE Instance",
            "title": "Containers & Services",
            "route": "/deploy/<instance_name>/",
            "icon": "bi-play-circle",
            "description": "Manage physical container deployments for the active HEAppE instance. Provides start, stop, restart, rebuild, and update actions for Docker Compose services.",
            "why_exists": "Administrators need a way to manage the backend server components (API service, database, Jaeger) without needing raw SSH access to the command line. This page provides a control panel for Docker containers.",
            "api_endpoints": [],
            "walkthrough": [
                "Select an instance and go to Containers & Services.",
                "Review container states (Running, Exited) and network port exposures.",
                "Trigger container actions (e.g., restart the API container) if changes were made to settings.",
                "Use the 'Update Instance' button to fetch new code and rebuild images."
            ],
            "ui_elements": [
                {"selector": ".container-row", "label": "Container Service Status", "explanation": "Shows container health status. Green denotes running services, gray denotes stopped services, and red indicates crash conditions."}
            ]
        },
        {
            "id": "configuration",
            "category": "HEAppE Instance",
            "title": "Instance Configuration",
            "route": "/deploy/<instance_name>/config/",
            "icon": "bi-gear",
            "description": "Directly edit the JSON configuration parameters (appsettings.json) of the HEAppE middleware deployment.",
            "why_exists": "Allows editing settings like database connections, connection strings, auth modes, and timeout periods in a web-based text editor with code syntax validation, automatically triggering container restarts on save.",
            "api_endpoints": [],
            "walkthrough": [
                "Navigate to Instance Configuration to load the JSON text editor.",
                "Edit values such as file locations, database parameters, or logging levels.",
                "Click 'Save Config' to write changes back to the server and restart affected container services."
            ],
            "ui_elements": [
                {"selector": ".json-editor-textarea", "label": "Interactive Code Editor", "explanation": "A text editor with automatic brackets completion, formatting, and syntax warnings."}
            ]
        },
        {
            "id": "backups",
            "category": "HEAppE Instance",
            "title": "Database Backups & Restore",
            "route": "/database-backups/",
            "icon": "bi-database",
            "description": "Manage database backups and restores for the HEAppE relational database (supported in HEAppE 6.4.0+).",
            "why_exists": "To prevent data loss from hardware failure or system corruptions. Enables scheduling full database backups, incremental transaction log backups, and performing restores.",
            "api_endpoints": [
                {"name": "heappe_management_backups_get", "description": "Fetches the list of database backup files available on the server."},
                {"name": "heappe_management_backup_database_post", "description": "Triggers a full database backup."},
                {"name": "heappe_management_restore_database_post", "description": "Restores the database from a backup file."}
            ],
            "walkthrough": [
                "Go to Database Backups to view chronological history of available backups.",
                "Click 'Backup Full Database' to initiate an immediate backup.",
                "To restore, select a backup file from the list, check log settings, and click 'Restore Database'."
            ],
            "ui_elements": [
                {"selector": ".btn-backup-full", "label": "Full Backup Button", "explanation": "Initiates an immediate complete snapshot backup of the SQL database on the server."}
            ]
        },
        {
            "id": "migration",
            "category": "HEAppE Instance",
            "title": "Migration Package",
            "route": "/migration-package/",
            "icon": "bi-box-arrow-up-right",
            "description": "Export or import the complete middleware configuration setup (clusters, projects, command templates, queues) as a secure encrypted `.enc` package.",
            "why_exists": "Allows copying setups from sandbox/development instances to staging or production instances. Passphrase protection ensures sensitive credentials stay encrypted.",
            "api_endpoints": [
                {"name": "heappe_management_export_migration_package_post", "description": "Generates and downloads the encrypted configuration package."},
                {"name": "heappe_management_import_migration_package_post", "description": "Uploads and restores configuration settings from an encrypted package file."}
            ],
            "walkthrough": [
                "Go to Migration Package.",
                "To Export: Enter a strong passphrase (minimum 12 characters, upper/lower cases, special characters) and click 'Export'. The browser downloads a `.enc` file.",
                "To Import: Select the `.enc` file, enter the identical decryption passphrase, and click 'Import'."
            ],
            "ui_elements": [
                {"selector": "#passphrase-input", "label": "Passphrase Field", "explanation": "A secure password entry with client-side password strength meter for encryption keys validation."}
            ]
        },
        {
            "id": "logs",
            "category": "HEAppE Instance",
            "title": "System Logs Viewer",
            "route": "/logs/",
            "icon": "bi-file-earmark-text",
            "description": "Inspect middleware execution logs. Offers search filters, error level charts, log detail previews, context analysis, and live streaming.",
            "why_exists": "Crucial for diagnostics. Combines DB log tables (performance monitoring, level filters) and raw text files on the disk (detailed debug trackback traces) in a unified UI.",
            "api_endpoints": [
                {"name": "logs_context_api", "description": "Fetches log records preceding a selected entry to analyze issues context."},
                {"name": "stream_logs", "description": "Establishes a Server-Sent Events stream to view live log lines in real-time."}
            ],
            "walkthrough": [
                "Open Logs Viewer to view recent logs. Filter by Log Level (e.g. Error, Critical) or search text.",
                "Click on an entry to open details showing thread info, class locations, and full exceptions.",
                "Click 'Show Context' to load events preceding the error.",
                "Switch to the File Log tab for real-time live streaming log logs."
            ],
            "ui_elements": [
                {"selector": "#logs-chart", "label": "Errors Chronology Chart", "explanation": "A line chart showing error occurrences per day, helping map when failures started."},
                {"selector": ".btn-stream", "label": "Live Stream Toggle", "explanation": "Starts a Server-Sent Events stream displaying logging lines as they are written to disk."}
            ]
        },
        {
            "id": "admin_accounts",
            "category": "Admin Panel",
            "title": "Admin Accounts",
            "route": "/admin-users/",
            "icon": "bi-shield-lock",
            "description": "Manage users who have access to this web administration panel. Available only to superusers.",
            "why_exists": "Ensures access security. Allows granting administration privileges, managing passwords, and creating superuser accounts.",
            "api_endpoints": [],
            "walkthrough": [
                "Navigate to Admin Accounts under the Admin Panel section.",
                "Click 'Create Admin User' to register a new administrator.",
                "Define permissions (Staff vs Superuser) and generate secure passwords.",
                "Use the edit layout to manage user details or change passwords."
            ],
            "ui_elements": [
                {"selector": ".superuser-badge", "label": "Clearance Level Badge", "explanation": "Identifies users: red badge indicates a Superuser; blue badge represents standard Staff accounts."}
            ]
        }
    ]

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json'
    if is_ajax:
        return JsonResponse(docs_data, safe=False)

    context = {
        "docs_data": docs_data,
        "docs_json": json.dumps(docs_data)
    }
    return render(request, "interactive_docs.html", context)
