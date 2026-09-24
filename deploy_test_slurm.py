#!/usr/bin/env python3
"""
HEAppE Test Slurm Simulator Deployment & Configuration Script
This script spins up a Docker-based Slurm cluster simulator (incorporating
Slurmctld, Slurmd, Slurmdbd, Munge, and MariaDB) and registers it automatically
with a HEAppE instance using the Py4HEAppE API.
"""

import os
import sys
import time
import socket
import argparse
import subprocess
import shutil
import uuid
import json
from datetime import datetime, timedelta

# Import HEAppE Client Core library
try:
    import py4heappe.heappe_v6.core as hp
except ImportError:
    # Attempt to use local path in the repository
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        import py4heappe.heappe_v6.core as hp
    except ImportError:
        print("ERROR: Could not import py4heappe. Please run this script with your project's python interpreter.")
        print("Example: .venv/bin/python deploy_test_slurm.py")
        sys.exit(1)


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def build_and_run_docker(container_name, port, slurm_user, acct_name):
    print("\n=== STEP 1: Deploying Dockerized Slurm Simulator ===")
    
    # 1. Check if docker is running
    try:
        subprocess.run(["docker", "info"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: Docker daemon is not running or docker command is not available.")
        sys.exit(1)

    # 2. Check if port is available
    if is_port_in_use(port):
        print(f"ERROR: Local port {port} is already in use. Please select a different port using --port.")
        sys.exit(1)

    # 3. Stop and remove existing container if it exists
    print(f"Checking for existing container '{container_name}'...")
    subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 4. Generate configurations in a temporary folder
    temp_dir = f"./slurm-temp-{uuid.uuid4().hex[:8]}"
    os.makedirs(temp_dir, exist_ok=True)
    print(f"Creating build files in temporary directory: {temp_dir}")

    try:
        # 4.1 slurm.conf
        slurm_conf = """ClusterName=simulator
SlurmctldHost=slurm-simulator
SlurmUser=slurm
SlurmdUser=root
SlurmdParameters=config_overrides
ProctrackType=proctrack/pgid
TaskPlugin=task/none
SlurmctldPidFile=/var/run/slurm/slurmctld.pid
SlurmdPidFile=/var/run/slurm/slurmd.pid
StateSaveLocation=/var/spool/slurmctld
SlurmdSpoolDir=/var/spool/slurmd
SlurmctldDebug=info
SlurmctldLogFile=/var/log/slurm/slurmctld.log
SlurmdDebug=info
SlurmdLogFile=/var/log/slurm/slurmd.log
JobAcctGatherType=jobacct_gather/linux
AccountingStorageType=accounting_storage/slurmdbd
AccountingStorageHost=slurm-simulator
AccountingStoragePort=6819
AccountingStorageEnforce=associations,limits
SelectType=select/cons_tres
SelectTypeParameters=CR_Core_Memory
GresTypes=gpu
NodeName=slurm-simulator NodeAddr=127.0.0.1 State=UNKNOWN CoresPerSocket=2 ThreadsPerCore=1 RealMemory=2000 Gres=gpu:2
PartitionName=test Nodes=slurm-simulator Default=YES MaxTime=INFINITE State=UP
"""
        with open(os.path.join(temp_dir, "slurm.conf"), "w") as f:
            f.write(slurm_conf)

        # 4.2 slurmdbd.conf
        slurmdbd_conf = """AuthType=auth/munge
DbdHost=slurm-simulator
DbdPort=6819
SlurmUser=slurm
StorageType=accounting_storage/mysql
StorageHost=localhost
StoragePort=3306
StorageUser=slurm
StoragePass=password
StorageLoc=slurm_acct_db
LogFile=/var/log/slurm/slurmdbd.log
PidFile=/var/run/slurm/slurmdbd.pid
"""
        with open(os.path.join(temp_dir, "slurmdbd.conf"), "w") as f:
            f.write(slurmdbd_conf)

        # 4.3 gres.conf
        gres_conf = """Name=gpu File=/var/tmp/gpu0,/var/tmp/gpu1
"""
        with open(os.path.join(temp_dir, "gres.conf"), "w") as f:
            f.write(gres_conf)

        # 4.4 entrypoint.sh
        entrypoint_content = f"""#!/bin/bash
set -e

ssh-keygen -A
mkdir -p /var/run/sshd

mkdir -p /var/run/munge /var/log/munge /etc/munge
if [ ! -f /etc/munge/munge.key ]; then
    dd if=/dev/urandom of=/etc/munge/munge.key bs=1 count=1024
fi
chown -R munge:munge /etc/munge /var/run/munge /var/log/munge
chmod 700 /etc/munge
chmod 755 /var/run/munge
chmod 755 /var/log/munge
chmod 400 /etc/munge/munge.key

echo "Starting Munge..."
sudo -u munge munged --force
sleep 2

mkdir -p /var/run/mysqld
chown mysql:mysql /var/run/mysqld
if [ ! -d "/var/lib/mysql/mysql" ]; then
    mysql_install_db --user=mysql --datadir=/var/lib/mysql
fi
/usr/bin/mysqld_safe --user=mysql &

echo "Waiting for MariaDB to start..."
until mysqladmin ping >/dev/null 2>&1; do
    sleep 1
done

mysql -e "CREATE DATABASE IF NOT EXISTS slurm_acct_db;"
mysql -e "CREATE USER IF NOT EXISTS 'slurm'@'localhost' IDENTIFIED BY 'password';"
mysql -e "GRANT ALL PRIVILEGES ON slurm_acct_db.* TO 'slurm'@'localhost';"
mysql -e "FLUSH PRIVILEGES;"

touch /var/tmp/gpu0 /var/tmp/gpu1
chmod 666 /var/tmp/gpu0 /var/tmp/gpu1

mkdir -p /var/spool/slurmctld /var/spool/slurmd /var/log/slurm /var/run/slurm
chown -R slurm:slurm /var/spool/slurmctld /var/spool/slurmd /var/log/slurm /var/run/slurm

chown slurm:slurm /etc/slurm/slurmdbd.conf
chmod 600 /etc/slurm/slurmdbd.conf
chown slurm:slurm /etc/slurm/slurm.conf
chmod 644 /etc/slurm/slurm.conf
chown slurm:slurm /etc/slurm/gres.conf
chmod 644 /etc/slurm/gres.conf

echo "Starting SlurmDBD..."
sudo -u slurm slurmdbd
sleep 3

echo "Configuring Slurm accounts..."
sacctmgr -i add cluster simulator || true
sacctmgr -i add account {acct_name} Description="Test Project Account" Organization="HEAppE" || true
sacctmgr -i add user {slurm_user} Account={acct_name} DefaultAccount={acct_name} || true

echo "Starting Slurmctld..."
sudo -u slurm slurmctld || true
sleep 2
echo "--- slurmctld.log ---"
cat /var/log/slurm/slurmctld.log || true
echo "---------------------"

echo "Starting Slurmd..."
slurmd -N slurm-simulator &
sleep 2
echo "--- slurmd.log ---"
cat /var/log/slurm/slurmd.log || true
echo "------------------"

echo "Updating Slurm node state..."
timeout 15 scontrol update nodename=slurm-simulator state=idle || true
sinfo || true

if [ ! -d "/home/{slurm_user}/.local_hpc_scripts" ]; then
    echo "Deploying local HPC helper scripts..."
    mkdir -p /home/{slurm_user}/.local_hpc_scripts
    if [ -d "/opt/heappe-scripts/LocalHPC/.local_hpc_scripts" ]; then
        cp -rf /opt/heappe-scripts/LocalHPC/.local_hpc_scripts/* /home/{slurm_user}/.local_hpc_scripts/
    else
        git clone --depth 1 --single-branch -b master --quiet https://github.com/It4innovations/HEAppE-scripts.git /tmp/heappe-scripts || true
        if [ -d "/tmp/heappe-scripts/LocalHPC/.local_hpc_scripts" ]; then
            cp -rf /tmp/heappe-scripts/LocalHPC/.local_hpc_scripts/* /home/{slurm_user}/.local_hpc_scripts/
            rm -rf /tmp/heappe-scripts
        fi
    fi
    chown -R {slurm_user}:{slurm_user} /home/{slurm_user}/.local_hpc_scripts
    chmod -R 755 /home/{slurm_user}/.local_hpc_scripts
fi

echo "Starting HEAppE key scripts watchdog..."
(
while true; do
    if [ -d "/home/{slurm_user}/.HEAppE" ]; then
        find /home/{slurm_user}/.HEAppE -type d -name ".key_scripts" 2>/dev/null | while read -r dir; do
            if [ ! -f "$dir/run_background_command.sh" ]; then
                echo "Watchdog: Injecting missing run_background_command.sh into $dir"
                cat << 'BG_EOF' > "$dir/run_background_command.sh"
#!/bin/bash
_evalBg() {{
    eval "$@" &>/dev/null & disown;
}}
BASE64_TEXT=$1
COMMAND=$(echo "${{BASE64_TEXT}}" | base64 -d)
_evalBg "${{COMMAND}}";
BG_EOF
                chmod 755 "$dir/run_background_command.sh"
                chown {slurm_user}:{slurm_user} "$dir/run_background_command.sh"
            fi
        done
    fi
    sleep 1
done
) &

echo "Starting SSH daemon..."
exec /usr/sbin/sshd -D
"""
        with open(os.path.join(temp_dir, "entrypoint.sh"), "w") as f:
            f.write(entrypoint_content)

        # 4.5 Dockerfile
        dockerfile_content = f"""FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \\
    openssh-server \\
    sudo \\
    munge \\
    slurm-wlm \\
    slurmdbd \\
    mariadb-server \\
    mariadb-client \\
    curl \\
    git \\
    && rm -rf /var/lib/apt/lists/*
RUN git clone --single-branch -b master --quiet https://github.com/It4innovations/HEAppE-scripts.git /opt/heappe-scripts || true
RUN useradd -m -s /bin/bash {slurm_user} && \\
    echo "{slurm_user}:pass" | chpasswd && \\
    echo "{slurm_user} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
RUN sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
COPY slurm.conf /etc/slurm/slurm.conf
COPY slurmdbd.conf /etc/slurm/slurmdbd.conf
COPY gres.conf /etc/slurm/gres.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"]
"""
        with open(os.path.join(temp_dir, "Dockerfile"), "w") as f:
            f.write(dockerfile_content)

        # Build Image
        print("Building Docker image 'slurm-simulator-img:latest'...")
        subprocess.run(["docker", "build", "-t", "slurm-simulator-img:latest", "."], cwd=temp_dir, check=True)
        print("Docker image built successfully.")

        # Run Container
        print(f"Running Docker container '{container_name}' mapping localhost:{port} -> container:22...")
        run_cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--hostname", "slurm-simulator",
            "--restart", "unless-stopped",
            "-p", f"{port}:22",
            "slurm-simulator-img:latest"
        ]
        subprocess.run(run_cmd, check=True)
        print(f"Container '{container_name}' started in background.")

    finally:
        # Cleanup temp build directory
        shutil.rmtree(temp_dir, ignore_errors=True)

    # Wait for SSH
    print(f"Waiting for SSH daemon to respond on port {port}...")
    start_time = time.time()
    ssh_ready = False
    while time.time() - start_time < 90:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect(("127.0.0.1", port))
                banner = s.recv(1024)
                if banner and b"SSH-" in banner:
                    ssh_ready = True
                    break
        except Exception:
            pass
        time.sleep(1)

    if not ssh_ready:
        print("ERROR: SSH service did not start in time inside container.")
        try:
            log_proc = subprocess.run(["docker", "logs", "--tail", "100", container_name], capture_output=True, text=True)
            print("Container logs:")
            print(log_proc.stdout + "\n" + log_proc.stderr)
        except Exception:
            pass
        sys.exit(1)
        
    print("SSH service is UP and responding!")
    print(f"Connection details: ssh {slurm_user}@localhost -p {port} (password: pass)")


def configure_heappe(heappe_url, heappe_user, heappe_pass, port, uid, slurm_user, acct_name):
    print("\n=== STEP 2: Configuring Slurm Cluster in HEAppE ===")
    
    # Clean URL format
    if not heappe_url.startswith("http"):
        heappe_url = "http://" + heappe_url
        
    print(f"Connecting to HEAppE API at {heappe_url} as '{heappe_user}'...")
    
    config = hp.Configuration()
    config.host = heappe_url
    config.verify_ssl = False # Set to False for local test setups

    # Try authentication
    config.api_key = {'X-API-Key': f"{heappe_user}:{heappe_pass}"}
    api_client = hp.ApiClient(config)
    api_client.set_default_header("X-API-Key", f"{heappe_user}:{heappe_pass}")
    
    ulm = hp.UserAndLimitationManagementApi(api_client)
    controller = hp.ManagementApi(api_client)
    
    session_code = None
    try:
        ulm.heappe_user_and_limitation_management_current_user_info_get()
        print("Successfully authenticated with X-API-Key.")
        try:
            r = ulm.heappe_user_and_limitation_management_authenticate_user_password_post(
                _preload_content=False,
                body={"Credentials": {"Username": heappe_user, "Password": heappe_pass}}
            )
            session_code = json.loads(r.data)
            print("Successfully acquired compatible SessionCode.")
        except Exception as e:
            print(f"Note: Could not fetch session code: {e}. Proceeding with API Key only.")
    except Exception as e_key:
        print(f"X-API-Key auth failed ({e_key}), attempting session authentication...")
        config.api_key = {}
        api_client.default_headers.pop("X-API-Key", None)
        try:
            r = ulm.heappe_user_and_limitation_management_authenticate_user_password_post(
                _preload_content=False,
                body={"Credentials": {"Username": heappe_user, "Password": heappe_pass}}
            )
            session_code = json.loads(r.data)
            print("Session authentication successful.")
        except Exception as e_fallback:
            print(f"ERROR: HEAppE authentication failed: {e_fallback}")
            sys.exit(1)

    # 1. Create Cluster
    print("Creating Cluster in HEAppE...")
    cluster_payload = {
        "Name": f"Slurm Cluster {uid}",
        "Description": f"Automated test Slurm cluster simulator (Port {port})",
        "MasterNodeName": "host.docker.internal",
        "SchedulerType": 4, # Slurm
        "ConnectionProtocol": 2, # SSH
        "TimeZone": "CET",
        "Port": port,
        "UpdateJobStateByServiceAccount": False,
        "DomainName": "",
        "ProxyConnectionId": None,
        "SessionCode": session_code
    }
    cluster_resp = controller.heappe_management_cluster_post(body=cluster_payload)
    cluster_dict = cluster_resp.to_dict() if hasattr(cluster_resp, 'to_dict') else cluster_resp
    cluster_id = cluster_dict.get('id') or cluster_dict.get('Id')
    print(f"Cluster created successfully (ID: {cluster_id}).")
    
    # 2. Create File Transfer Method
    print("Creating File Transfer Method (SFTP/SCP) in HEAppE...")
    ftm_payload = {
        "ClusterId": cluster_id,
        "ServerHostname": "host.docker.internal",
        "Protocol": 2, # SFTP/SCP
        "Port": port,
        "SessionCode": session_code
    }
    ftm_resp = controller.heappe_management_file_transfer_method_post(body=ftm_payload)
    ftm_dict = ftm_resp.to_dict() if hasattr(ftm_resp, 'to_dict') else ftm_resp
    ftm_id = ftm_dict.get('id') or ftm_dict.get('Id')
    print(f"File Transfer Method created successfully (ID: {ftm_id}).")

    # 3. Create Queue Groups (NodeType Aggregations)
    print("Creating Queue Groups in HEAppE...")
    now_aware = datetime.utcnow() - timedelta(minutes=5)
    valid_to = datetime.utcnow() + timedelta(days=365)
    
    cpu_group_payload = {
        "Name": f"Slurm CPU Group {uid}",
        "Description": "Slurm CPU Queue Group",
        "AllocationType": "CN",
        "ValidityFrom": now_aware.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ValidityTo": valid_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "SessionCode": session_code
    }
    cpu_group_resp = controller.heappe_management_cluster_node_type_aggregation_post(body=cpu_group_payload)
    cpu_group_dict = cpu_group_resp.to_dict() if hasattr(cpu_group_resp, 'to_dict') else cpu_group_resp
    cpu_group_id = cpu_group_dict.get('id') or cpu_group_dict.get('Id')
    print(f"CPU Queue Group created (ID: {cpu_group_id}).")

    gpu_group_payload = {
        "Name": f"Slurm GPU Group {uid}",
        "Description": "Slurm GPU Queue Group",
        "AllocationType": "ACN",
        "ValidityFrom": now_aware.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ValidityTo": valid_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "SessionCode": session_code
    }
    gpu_group_resp = controller.heappe_management_cluster_node_type_aggregation_post(body=gpu_group_payload)
    gpu_group_dict = gpu_group_resp.to_dict() if hasattr(gpu_group_resp, 'to_dict') else gpu_group_resp
    gpu_group_id = gpu_group_dict.get('id') or gpu_group_dict.get('Id')
    print(f"GPU Queue Group created (ID: {gpu_group_id}).")

    # 4. Create Accounting Formulas
    print("Creating Accounting Formulas...")
    cpu_acc_payload = {
        "Formula": "NumCPUs * RunTime",
        "ValidityFrom": now_aware.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ValidityTo": valid_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "SessionCode": session_code
    }
    cpu_acc_resp = controller.heappe_management_accounting_post(body=cpu_acc_payload)
    cpu_acc_dict = cpu_acc_resp.to_dict() if hasattr(cpu_acc_resp, 'to_dict') else cpu_acc_resp
    cpu_acc_id = cpu_acc_dict.get('id') or cpu_acc_dict.get('Id')

    gpu_acc_payload = {
        "Formula": "NumNodes * RunTime * 5",
        "ValidityFrom": now_aware.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ValidityTo": valid_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "SessionCode": session_code
    }
    gpu_acc_resp = controller.heappe_management_accounting_post(body=gpu_acc_payload)
    gpu_acc_dict = gpu_acc_resp.to_dict() if hasattr(gpu_acc_resp, 'to_dict') else gpu_acc_resp
    gpu_acc_id = gpu_acc_dict.get('id') or gpu_acc_dict.get('Id')

    # Map formulas
    controller.heappe_management_cluster_node_type_aggregation_accounting_post(
        body={"ClusterNodeTypeAggregationId": cpu_group_id, "AccountingId": cpu_acc_id, "SessionCode": session_code}
    )
    controller.heappe_management_cluster_node_type_aggregation_accounting_post(
        body={"ClusterNodeTypeAggregationId": gpu_group_id, "AccountingId": gpu_acc_id, "SessionCode": session_code}
    )
    print("Accounting Formulas created and mapped.")

    # 5. Create Queues (Node Types)
    print("Creating Queues...")
    cpu_queue_payload = {
        "Name": "cpu",
        "Description": "Slurm CPU partition",
        "NumberOfNodes": 1,
        "CoresPerNode": 2,
        "Queue": "test",
        "QualityOfService": None,
        "MaxWalltime": 999999,
        "ClusterAllocationName": "simulator",
        "ClusterId": cluster_id,
        "FileTransferMethodId": ftm_id,
        "ClusterNodeTypeAggregationId": cpu_group_id,
        "SessionCode": session_code
    }
    controller.heappe_management_cluster_node_type_post(body=cpu_queue_payload)

    gpu_queue_payload = {
        "Name": "gpu",
        "Description": "Slurm GPU partition",
        "NumberOfNodes": 1,
        "CoresPerNode": 2,
        "Queue": "test",
        "QualityOfService": None,
        "MaxWalltime": 999999,
        "ClusterAllocationName": "simulator",
        "ClusterId": cluster_id,
        "FileTransferMethodId": ftm_id,
        "ClusterNodeTypeAggregationId": gpu_group_id,
        "SessionCode": session_code
    }
    controller.heappe_management_cluster_node_type_post(body=gpu_queue_payload)
    print("CPU ('cpu') and GPU ('gpu') queues configured.")

    # 6. Create Project
    print("Creating Project...")
    project_payload = {
        "Name": f"Slurm Project {uid}",
        "Description": "Automatically generated test project for Slurm simulator",
        "AccountingString": acct_name,
        "StartDate": now_aware.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "EndDate": valid_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "UsageType": 1,
        "UseAccountingStringForScheduler": True,
        "IsOneToOneMapping": False,
        "PIEmail": "",
        "SessionCode": session_code
    }
    project_resp = controller.heappe_management_project_post(body=project_payload)
    project_dict = project_resp.to_dict() if hasattr(project_resp, 'to_dict') else project_resp
    project_id = project_dict.get('id') or project_dict.get('Id')
    print(f"Project created successfully (ID: {project_id}).")

    # 7. Assign Project to Cluster
    print("Assigning Project to Cluster...")
    assign_payload = {
        "ProjectId": project_id,
        "ClusterId": cluster_id,
        "ScratchStoragePath": f"/home/{slurm_user}",
        "PermanentStoragePath": f"/home/{slurm_user}",
        "ProjectStoragePath": f"/home/{slurm_user}",
        "SessionCode": session_code
    }
    controller.heappe_management_project_assignment_to_cluster_post(body=assign_payload)

    # 8. Assign Project to Groups
    controller.heappe_management_project_cluster_node_type_aggregation_post(
        body={"ProjectId": project_id, "ClusterNodeTypeAggregationId": cpu_group_id, "AllocationAmount": 10000, "SessionCode": session_code}
    )
    controller.heappe_management_project_cluster_node_type_aggregation_post(
        body={"ProjectId": project_id, "ClusterNodeTypeAggregationId": gpu_group_id, "AllocationAmount": 10000, "SessionCode": session_code}
    )
    print("Project successfully assigned to Cluster and Queue Groups.")

    # 9. Create SSH Authentication Credentials
    print(f"Creating SSH Authentication Credentials for user '{slurm_user}'...")
    cred_payload = {
        "Credentials": [{"Username": slurm_user, "Password": "pass"}],
        "ProjectId": project_id,
        "SessionCode": session_code
    }
    controller.heappe_management_generate_secure_shell_key_post(body=cred_payload)

    # 10. Initialize script directories
    print("Initializing project script directory on the HPC node...")
    init_payload = {
        "ProjectId": project_id,
        "Username": slurm_user,
        "OverwriteExistingProjectRootDirectory": True,
        "SessionCode": session_code
    }
    controller.heappe_management_initialize_cluster_script_directory_post(body=init_payload)

    print("\n=== SETUP SUCCESSFUL ===")
    print(f"Successfully configured Slurm Cluster (ID: {cluster_id}) and Project (ID: {project_id}).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy and configure a test Slurm cluster simulator for HEAppE.")
    
    parser.add_argument("--heappe-url", default="http://localhost:8080", help="URL of the HEAppE instance API")
    parser.add_argument("--heappe-user", required=True, help="HEAppE API Administrator login")
    parser.add_argument("--heappe-pass", required=True, help="HEAppE API Administrator password")
    
    parser.add_argument("--port", type=int, default=2222, help="Host SSH port to map to the container (default: 2222)")
    parser.add_argument("--container-name", default="slurm-simulator-local", help="Docker container name (default: slurm-simulator-local)")
    
    parser.add_argument("--skip-docker", action="store_true", help="Skip Docker build and execution step")
    parser.add_argument("--skip-heappe", action="store_true", help="Skip HEAppE cluster registration & configuration step")

    args = parser.parse_args()

    uid = str(uuid.uuid4())[:8]
    acct_name = f"a{uid}"
    slurm_user = f"u{uid}"

    if not args.skip_docker:
        build_and_run_docker(args.container_name, args.port, slurm_user, acct_name)
    else:
        # Fallback names in case docker was skipped
        acct_name = "atest"
        slurm_user = "heappeslurm"
        print("Skipping Docker deployment step as requested.")

    if not args.skip_heappe:
        configure_heappe(args.heappe_url, args.heappe_user, args.heappe_pass, args.port, uid, slurm_user, acct_name)
    else:
        print("Skipping HEAppE configuration step as requested.")

    print("\n=== ALL DONE ===")
