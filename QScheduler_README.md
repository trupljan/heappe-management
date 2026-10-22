# QScheduler in HEAppE Management

This guide is for HEAppE Management administrators. It covers deploying or registering a
[QScheduler](https://github.com/It4innovations/qscheduler) instance, connecting HEAppE instances to it, and
adding quantum machines as HEAppE clusters.

- [Concepts](#concepts)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [QScheduler page](#qscheduler-page)
  - [Deploy a new instance](#deploy-a-new-instance)
  - [Register an existing instance](#register-an-existing-instance)
  - [Instance card](#instance-card)
  - [Update](#update)
  - [Restart](#restart)
  - [Undeploy / Unregister](#undeploy--unregister)
- [Assigning HEAppE instances](#assigning-heappe-instances)
  - [Notifications](#notifications)
  - [Edit an assignment](#edit-an-assignment)
  - [Unassign](#unassign)
- [Clusters page: quantum machines](#clusters-page-quantum-machines)
  - [Add a quantum machine](#add-a-quantum-machine)
  - [Remove a quantum machine](#remove-a-quantum-machine)
- [SSH directly into the QScheduler container](#ssh-directly-into-the-qscheduler-container)
- [When QScheduler is restarted](#when-qscheduler-is-restarted)
- [Security notes](#security-notes)
- [Troubleshooting](#troubleshooting)
- [Action reference](#action-reference)

---

## Concepts

| Term | Meaning |
|---|---|
| **QScheduler instance** | One QScheduler service (REST API + PostgreSQL database). It can be **shared by several HEAppE instances**. |
| **Machine** | A quantum backend registered in a QScheduler instance (`test` simulator or `iqm`). A machine can be used by several HEAppE instances. |
| **HEAppE cluster** | Each HEAppE instance has its **own cluster per machine** (scheduler type *QScheduler*, protocol *HTTP*). The machine name is the cluster's queue. |
| **Assignment** | A HEAppE instance allowed to use a QScheduler instance. It covers network access and, optionally, notifications. |
| **Notifier** | A named callback target inside QScheduler (`URL` + `token`). **Each HEAppE cluster has its own notifier** (`<HEAppE identifier>.<machine>`) with its own token, so task and session events reach the right HEAppE and are authenticated per cluster. The token is always stored in HEAppE Vault. |

Where things are managed:

- **QScheduler page** (sidebar → *Infrastructure* → *QScheduler*): instances (deploy, register, update, restart,
  undeploy) and assignments of HEAppE instances (including notification settings).
- **Clusters page** (*Clusters* → *QScheduler* menu): adding and removing quantum machines **for the HEAppE instance
  you are currently working with**. When the assignment has notifications on, adding a machine also creates the
  cluster's notifier and token.

---

## Requirements

- Docker on the HEAppE Management host (for deployed and local instances).
- HEAppE **6.6.0 or newer** for all QScheduler features (assignments, quantum machines, notifications). HEAppE
  6.6.0 introduced the QScheduler notifier settings (`QSchedulerNotifier`, `QSchedulerNotifyToken`). For older
  HEAppE instances:
  - the **QScheduler** menu on the Clusters page is hidden and *QScheduler* is not offered as a scheduler type
    for new clusters (existing QScheduler clusters can still be opened and edited);
  - they cannot be assigned to a QScheduler instance, either through *Assign* or when deploying;
  - quantum machines cannot be added. Removing a machine and unassigning still work, so old setups can be cleaned
    up.

  An unknown version (the HEAppE health API does not answer) counts as older.
- A QScheduler version with notifier support (the `qscheduler notifier` command). Registering an older QScheduler
  fails with a message about `notifier list`.
- After upgrading HEAppE Management, run the database migration once:

  ```bash
  python manage.py migrate
  ```

---

## Quick start

1. **QScheduler page → Deploy New.** Keep the defaults (build `main` from the official repository, new PostgreSQL)
   and, under *Assignment*, select your HEAppE instance with *Enable notifications* on. Click **Deploy**.
   The first image build compiles QScheduler from source and takes several minutes.
2. **Clusters page → QScheduler → Add quantum machine.** Select the instance, keep *Register new machine* with the
   `test` backend, tick *Create HEAppE project* and enter a QPU allocation (for example `36000` seconds). Click
   **Add Machine**.
3. Open the new cluster (link in the progress dialog) and submit a test job through
   `/heappe/QScheduler/CreateAndSubmitJob`.

To make the same machine available to a second HEAppE instance: on the QScheduler page click **Assign** on the
instance card, select the second HEAppE instance, then switch to that HEAppE instance and use **Add quantum machine →
Use existing machine (shared)**.

Every operation runs in the background. A progress dialog shows the log, and only one QScheduler operation can run
at a time. The log of the last operation is also stored in `qscheduler_setup.log` in the project directory.

---

## QScheduler page

### Deploy a new instance

**Deploy New** starts a QScheduler service on the HEAppE Management Docker host. No machine is registered at this
step; machines are added from the Clusters page.

| Section | Field | Description |
|---|---|---|
| Image | *Build from git (branch / tag)* | Builds the image with `docker build -t <image> <repository>#<branch or tag>`. An existing image with the same name is reused unless *Rebuild the image* is ticked. |
| | *Image available on this host* | Uses an image that is already on the Docker host (pick from the suggestions or type its name). |
| | Git repository, Branch / tag, Image | Defaults: `https://github.com/It4innovations/qscheduler.git`, `main`, `qscheduler:latest`. |
| | Branch / tag picker | When the repository can be read, *Branch / tag* is a list of its branches (default branch first) and tags (newest first); *Other (type manually)...* allows any other ref. The list is loaded again when the repository URL changes. If the repository cannot be read, the field stays a plain text input. See [Branch / tag list](#branch--tag-list). |
| Service | Container name | Default `qscheduler-<id>`. Also the instance name and the host name HEAppE uses. |
| | Service port | Port of the REST API inside the container (default `4300`). |
| | Publish on host | Optional. Publishes the port on `127.0.0.1` only. |
| | Database | *Deploy new PostgreSQL*: creates the container `<name>-pgsql`, the internal network `<name>_db_net` and the volume `<name>-pgdata`. *Use existing database*: enter `DATABASE_URL` (`postgres://...`) and optionally the Docker network on which the database is reachable. |
| Assignment | Assign HEAppE instance | Optional. Assigns a HEAppE instance right after the deployment (see [Assigning HEAppE instances](#assigning-heappe-instances)). |
| | Enable notifications | Turns notifications on for that HEAppE instance; notifiers are created later, one per cluster. The HEAppE instance must run 6.6.0 or newer, otherwise the deployment is refused before it starts. |

The service container gets a Docker healthcheck (`GET /health`). The deployment waits until it is healthy.

#### Branch / tag list

The management host reads the branches and tags:

| Repository URL | Source |
|---|---|
| `https://github.com/<owner>/<repo>(.git)` | GitHub API (anonymous: 60 requests per hour per host IP; results are cached for 5 minutes). |
| Other `http(s)://` host | GitLab API (`/api/v4/projects/<path>`), e.g. `gitlab.com` or a self-hosted GitLab. |
| `git@…` / `ssh://…`, or when the API fails | `git ls-remote` on the management host (needs `git`; SSH uses the keys of the user running HEAppE Management, without prompts). |

Only public repositories (or those readable by the management host's git credentials) are listed. Up to 200 branches
and 200 tags are shown.

### Register an existing instance

**Register Existing** adds a QScheduler that is already running. Choose how HEAppE Management reaches it:

| Mode | How commands are run | Typical use |
|---|---|---|
| **Container on this Docker host** | `docker exec <container> qscheduler ...` on the management host | A QScheduler started manually or by another tool on the same host. |
| **Remote: SSH to the VM running the container** | SSH to the VM, then `docker exec <container> qscheduler ...` there | QScheduler in Docker on another machine. Full management. |
| **Remote: SSH directly into the QScheduler container** | SSH into the container (it must run an SSH server), then `qscheduler ...` | Docker on the remote machine is not accessible. **Limited management**, see [below](#ssh-directly-into-the-qscheduler-container). |

Fields:

| Field | Modes | Description |
|---|---|---|
| SSH host, SSH port, SSH user | both SSH modes | SSH port defaults to `22`. |
| SSH private key | both SSH modes | Paste the key or load it from a file. Ed25519, ECDSA and RSA keys in OpenSSH or PEM format are supported. |
| Key passphrase | both SSH modes | Only for an encrypted key. |
| Container | local, SSH to VM | Name of the QScheduler container. For the local mode the page suggests containers that run `qscheduler serve`. |
| Docker command | SSH to VM | `docker`, or `sudo -n docker` when the SSH user needs passwordless sudo for Docker. |
| DATABASE_URL | SSH into container | Optional. By default it is read from the environment of the service process (PID 1) in the container. |
| Restart command | SSH into container | Default `kill -TERM 1`. Leave empty to restart manually. See [below](#ssh-directly-into-the-qscheduler-container). |
| Host as seen from HEAppE | all | Host name or IP under which HEAppE reaches the QScheduler REST API. Default: the container name (local) or the SSH host (remote). |
| Service port | all | Detected from the container command for Docker modes; otherwise `4300`. |
| Name | all | Name shown in HEAppE Management. Default: container name or SSH host. |

Registration checks that `GET /health` returns `200`, reads the version and lists the notifiers. For SSH modes the
server's host key is saved on first connection and checked on every later connection.

### Instance card

Each instance is shown as a card with:

- kind, health (`healthy`, `HTTP <code>` or `unreachable`) and version,
- the endpoint HEAppE uses (`host:port`), SSH target, container and image source,
- *restart pending* when a change was written but the service has not been restarted yet,
- **Machines** registered in the instance, with their backend. Listing needs the `postgres:16` image on the Docker
  host of the instance (it is never downloaded only for this) or `psql` inside the container. Otherwise the list
  shows *cannot be listed*,
- **Notifiers**, one per HEAppE cluster. A notifier whose name is not `<identifier>.<machine>` of an assigned
  HEAppE instance is marked *unmanaged*: HEAppE Management does not create, update or remove it. Typically a leftover
  of the old one-notifier-per-HEAppE scheme or one created by hand. It can be removed, see below,
- **Assigned HEAppE instances**, with notification state, notifier name pattern, callback URL and network.

#### Remove an unmanaged notifier

Optional, next to an *unmanaged* notifier: **remove**. Only remove a notifier when you know what it was created for:
QScheduler calls it for every task and session that names it (`notify=<name>`), and HEAppE clusters with callbacks
enabled do not poll task state, so anything still using it **stops receiving job updates**.

The dialog requires ticking *I know what this notifier is used for...*. HEAppE Management then refuses the removal
when a QScheduler cluster of an assigned HEAppE instance uses the notifier, or when an assigned HEAppE instance cannot
be checked. It **cannot check** HEAppE instances that are not assigned here (or not registered in HEAppE Management),
other clients calling QScheduler directly, or tasks and sessions already submitted with the notifier. On success it
runs `qscheduler notifier remove <name>` and restarts QScheduler once. Managed notifiers are removed with their
cluster or by editing the assignment.

Instances deployed with an earlier version of HEAppE Management (from the Clusters page) are imported automatically
when the page is opened. The HEAppE instance they were deployed for stays assigned, with notifications off.

### Update

**Actions → Update** (Docker-based instances only: deployed, local container, SSH to VM).

- *Build from git*: always rebuilds the image from the given repository and branch / tag, on the Docker host of the
  instance.
- *Existing image*: switches to an image already present on that Docker host.

*Branch / tag* offers the same list as in the deploy dialog.

The container is recreated with the same configuration (environment, database, networks, published ports, restart
policy). Machines, notifiers and projects are kept in PostgreSQL. If the new container does not become healthy, the
previous one is restored.

### Restart

**Actions → Restart** stops QScheduler gracefully (pending state, including running session time, is written to the
database) and starts it again. Tasks still running on a backend are re-attached. Use it, for example, after changing
machines manually or to clear *restart pending*.

For an instance reached over SSH into the container **without a restart command**, the action is called **Confirm
manual restart**. Restart the container yourself first; the action then checks that `/health` answers and clears
*restart pending*.

### Undeploy / Unregister

Refused while any HEAppE instance is assigned. [Unassign](#unassign) them first.

- **Undeploy** (instances deployed by HEAppE Management): removes the QScheduler container, its PostgreSQL container
  and database network. The database volume is removed only when *Also delete the database volume* is ticked. The
  image is kept.
- **Unregister** (registered instances): removes the instance from HEAppE Management only. The QScheduler service
  keeps running.

### Instance removed without HEAppE Management

When the container **still exists** but QScheduler does not answer (stopped, crashed or hanging), the card shows
*not responding* and a **Try restart** button. It runs the normal restart: `docker restart` (which also starts a
stopped container) or the restart command of an "SSH into container" instance (*Confirm manual restart* when it has
none), then waits for `/health`. If the service does not come back, the operation log shows the container's last log
lines.

When the QScheduler service disappears behind HEAppE Management's back (container removed by hand, VM reinstalled),
the instance card shows:

- **Missing**: the container no longer exists (deployed, local and "SSH to VM" instances).
- **Unreachable**: it cannot be told whether the container exists (Docker or SSH unavailable; for an "SSH into
  container" instance the SSH login fails, which looks the same as a removed container). Check the host before
  deleting anything.

HEAppE Management never resolves this on its own. **Resolve...** (on the card or in *Actions*) offers three choices:

| Choice | What happens | Undo |
|---|---|---|
| **Archive** | The record, its assignments and all HEAppE clusters are kept **unchanged** (jobs on them fail until QScheduler is back). The card shows *Archived* with the reason; restart, update, assign, unassign and undeploy are disabled, no machine can be added, and *Remove quantum machine* deletes only the HEAppE cluster without contacting QScheduler. | *Restore*, or *Unarchive* when the service answers again (e.g. it was only down). |
| **Restore** | Deploys QScheduler again and reassigns everything (see below). | – |
| **Delete with entities** | Deletes what belonged to the instance, as selected (see below), and forgets it. | No. |

An archived instance offers **Restore...**, **Delete with entities...** and, once its service answers again,
**Unarchive**.

#### Delete with entities

A preview lists, per assigned HEAppE instance, its clusters on the instance and the projects and queue groups used
**only** by those clusters. Select what to delete and type the instance name to confirm:

| Option | Default | Deletes |
|---|---|---|
| HEAppE clusters | on | The clusters on this instance (with their queues and file transfer methods). Their `QSchedulerNotifyToken` is removed from Vault first. Off: the clusters are kept and only the instance is forgotten. |
| Projects used only by these clusters | off | Those projects (needs *HEAppE clusters*). |
| Queue groups used only by these clusters | off | Those queue groups with their accounting formulas (if not shared) and project allocations (needs *HEAppE clusters*). |
| Leftover PostgreSQL container and network | on | Deployed instances only. |
| Database volume | off | Deployed instances only (needs the previous option). |
| Skip unreachable HEAppE instances | off | Shown when an assigned HEAppE cannot be reached. Without it nothing is deleted; with it, its clusters stay and point to the deleted instance. |

All HEAppE instances are read before anything is deleted. When a deletion fails, the instance is kept so that it
can be retried; projects, allocations and credentials not selected are kept.

#### Restore

Restore deploys QScheduler on the HEAppE Management Docker host the same way as *Deploy New* (instances that were
registered, local or remote, become deployed instances):

- **Image**: the previous branch / tag / image is preselected; any other branch, tag or local image can be chosen.
- **Service**: container name and port (default: the previous ones). When they differ from the old endpoint, the
  clusters and their file transfer methods are pointed to the new one.
- **Database**:
  - *Deploy new PostgreSQL*: a fresh database; old leftovers of the same name (PostgreSQL container, network,
    volume) are removed.
  - *Reuse the old database* (deployed instances under their original name): the old PostgreSQL container if it
    still exists, or the kept volume with the stored password. Machines that still exist in it are kept.
  - *Use existing database*: a `DATABASE_URL`.
- **Machines used by the clusters**: one row per machine, prefilled from the definition stored when it was added
  (backend, queue size, limits, IQM URL and device). The **IQM token is never stored** and must be entered again.
  With a reused database, *exists in reused DB* skips a machine.
- **HEAppE clusters to reassign**: the clusters of every assigned HEAppE instance on the old endpoint.

After the service is healthy, Restore registers the missing machines, creates **one notifier per cluster with a new
token** (for HEAppE instances with notifications on), restarts QScheduler once, and updates every cluster with its
new notifier and token (stored in Vault) and, if changed, the new endpoint. The record is then no longer archived.
If a machine cannot be registered, its clusters are reported and the others are restored. An unreachable HEAppE
instance stops the restore before anything changes, unless *Skip unreachable HEAppE instances* is ticked; its
clusters can be reassigned later with *Edit assignment → Generate new tokens*.

---

## Assigning HEAppE instances

**Assign** on an instance card. A HEAppE instance must be assigned before its Clusters page can add machines from
that QScheduler. Only HEAppE **6.6.0 or newer** can be assigned; the dialog shows the version of the selected
instance and disables *Save* for older ones.

What an assignment does:

1. **Network** (QScheduler on the HEAppE Management Docker host): the QScheduler container joins the Docker network
   of the HEAppE API container. The HEAppE API is restarted briefly when the network is joined for the first time.
   A remote QScheduler must already be reachable from HEAppE at *Host as seen from HEAppE* and the service port.
2. **Reachability check**: when the HEAppE API container runs on this host, `GET /health` is requested from inside
   it.
3. **Notifications** on or off and the **callback URL** (see below). No notifier is created at this point.
4. **Identifier check**: two HEAppE instances with the same instance identifier cannot be assigned to the same
   QScheduler, because their notifier names would clash.

### Notifications

When enabled, QScheduler sends task completion and session open/close events to HEAppE instead of HEAppE polling for
them.

| Field | Description |
|---|---|
| Task and session notifications | On or off for all clusters of this HEAppE instance on this QScheduler. |
| Callback URL | HEAppE `TaskCallback` endpoint **as reachable from the QScheduler host**, shared by all notifiers of this HEAppE instance. Filled in automatically (`http://<heappe container>:80/heappe/JobManagement/TaskCallback`) only when both run on this Docker host; otherwise required, for example `https://heappe.example.org/heappe/JobManagement/TaskCallback`. |

**Notifiers are per cluster.** They are created on the Clusters page when a quantum machine is added (see
[Add a quantum machine](#add-a-quantum-machine)):

- name `<HEAppE identifier>.<machine>`, for example `heappe-dev.SimulatorMachine`. The identifier is the HEAppE
  instance identifier (*InstanceIdentifierPath*),
- a new random token for every cluster,
- `qscheduler notifier add <name> --url <callback URL> --token <token>` in QScheduler,
- on the HEAppE cluster: `EnableCallback = true`, `QSchedulerNotifier = <name>`, `QSchedulerNotifyToken = <token>`.
  The token is **always stored in HEAppE Vault**; the cluster configuration shows only `********`.

A machine shared by several HEAppE instances therefore has one notifier per HEAppE instance, for example
`heappe-dev.SimulatorMachine` and `heappe-prod.SimulatorMachine`.

With notifications off, clusters are created with `EnableCallback = false` and HEAppE polls QScheduler for task state.

### Edit an assignment

The pencil icon in the assignments table. You can turn notifications on or off, change the callback URL, or tick
**Generate new tokens for all clusters of this HEAppE**.

When any of these change, the existing clusters of this HEAppE instance on this QScheduler are updated in one go:

- *Notifications turned on, callback URL changed, or new tokens requested*: each cluster's notifier is recreated with
  a **new token**, QScheduler restarts once, and the new tokens are written to the clusters (in Vault).
- *Notifications turned off*: the clusters' notifiers are removed, QScheduler restarts once, and the clusters get
  `EnableCallback = false`; their tokens are deleted from Vault.

Saving without changes does not touch notifiers or clusters.

### Unassign

The ✕ icon in the assignments table.

- Refused while the HEAppE instance still has clusters on this QScheduler. Remove them first on its Clusters page.
- *Force* skips that check when the HEAppE API cannot be reached.
- Removes leftover notifiers of this HEAppE instance (names starting with `<identifier>.`; QScheduler is restarted if
  there were any) and disconnects the QScheduler container from the HEAppE network.

---

## Clusters page: quantum machines

The **QScheduler** menu on the Clusters page works with the HEAppE instance currently selected in HEAppE Management.
It is shown only when that instance runs HEAppE 6.6.0 or newer.

### Add a quantum machine

Only QScheduler instances **assigned** to the current HEAppE instance are offered.

| Section | Field | Description |
|---|---|---|
| Quantum machine | *Register new machine* | Registers a new machine in QScheduler (`qscheduler machine add`). Refused if a machine with that name already exists. |
| | *Use existing machine (shared)* | Uses a machine that is already registered (for example by another HEAppE instance). The machine itself is not changed. It is checked over the REST API. |
| | Machine name | Up to 30 characters (letters, digits, `_`, `.`, `-`). Becomes the HEAppE queue. Registered machines are suggested. |
| | Backend | `test` (in-process simulator) or `iqm`. For `iqm`: server URL, device name (for example `star24`), token and poll interval (for example `500ms`). |
| | Machine limits | Queue size (`4`), max session time (`2h`), default task time limit (`1h`), limit check interval (`2s`), max clock skew (`4s`). Durations need a unit. |
| HEAppE cluster | Cluster name | Default: the machine name. |
| | Accounting formula | Default `exectime_ms/1000` (QPU seconds). |
| | Use sessions by default | Sets `QSchedulerUseSessions`. |
| | Create HEAppE project | Creates a project (usage type QPU seconds) assigned to the cluster, and a service credential. Optional *custom project name* and *QPU allocation (seconds)*. Without an allocation, HEAppE rejects jobs for the project until one is added. |

Created in HEAppE: cluster, file transfer method (HTTP), QPU queue group with the accounting formula, queue,
optionally project + allocation + credential.

**Notifier of the cluster** (when the assignment has notifications on): a new notifier
`<HEAppE identifier>.<machine>` with a new token is registered in QScheduler, and the cluster is created with
`EnableCallback = true`, `QSchedulerNotifier` and `QSchedulerNotifyToken` (stored in HEAppE Vault). This applies to new
and to shared machines alike: a shared machine gets an additional notifier for this HEAppE instance.

QScheduler restarts once when anything was registered (new machine and/or notifier). If creating the cluster fails,
the notifier is removed again.

> QScheduler project names are global within a QScheduler instance and are shared by all HEAppE instances using it.
> HEAppE registers the project in QScheduler on the first job, using the project's accounting string. Do not reuse
> an accounting string of another HEAppE instance on the same QScheduler unless you want them to share the budget.

### Cluster detail of a QScheduler cluster

The cluster detail page shows a **QScheduler cluster** badge next to *Cluster Configuration*. Its *Webhook & Callback
Notifications* section contains the cluster's notifier settings instead of the generic webhook fields:

| Field | Key | Description |
|---|---|---|
| Enable Callback Notifications | `EnableCallback` | QScheduler pushes task and session events; HEAppE stops polling. |
| QScheduler Notifier | `QSchedulerNotifier` | Name of the cluster's notifier in QScheduler (`<HEAppE identifier>.<machine>`). |
| QScheduler Notify Token | `QSchedulerNotifyToken` | Token of that notifier, always stored in HashiCorp Vault and shown as `********`. Leave it to keep the token, clear it to remove it. |

These fields must match the notifier registered in QScheduler. Prefer changing them through the assignment on the
QScheduler page (*Generate new tokens*), which updates QScheduler and HEAppE together.

The notifier URL (the HEAppE TaskCallback endpoint) is stored in QScheduler, not in the cluster. The section shows a
hint where to change it: on the QScheduler page, edit the HEAppE instance's assignment (pencil icon) and set
**Callback URL**. Saving recreates the notifiers of all clusters of that HEAppE on the instance with new tokens and
restarts QScheduler.

### Remove a quantum machine

Select one of the current HEAppE instance's QScheduler clusters.

- The **HEAppE cluster is deleted**. Projects, allocations and credentials are kept; delete them in HEAppE if no
  longer needed.
- The **cluster's notifier** (`<HEAppE identifier>.<machine>`) is removed from QScheduler, and QScheduler restarts.
  Notifiers of other HEAppE instances sharing the machine are kept.
- **Also remove the machine from QScheduler** (optional, off by default): runs `qscheduler machine remove` and
  restarts QScheduler. The machine may be shared, so **clusters of other HEAppE instances using it stop working**.
  - Without *Force*, QScheduler refuses to remove a machine that still has tasks or sessions; the HEAppE cluster is
    then not deleted either.
  - *Force* also deletes the machine's tasks and sessions. Time they consumed is not returned to their projects.
- The option is unavailable when the cluster's QScheduler is not registered in HEAppE Management.

---

## SSH directly into the QScheduler container

Use this mode only when the Docker host of a remote QScheduler cannot be accessed. HEAppE Management then talks only
to a shell inside the QScheduler container. Wherever such an instance is involved, the page shows a yellow
**SSH into container – Limited management** warning.

### How it works

| Task | How it is done |
|---|---|
| QScheduler commands (machines, notifiers) | `qscheduler ...` in the container, with `DATABASE_URL` from the registration form or from the environment of PID 1 (`/proc/1/environ`). |
| Health and version | `curl` (or `bash` `/dev/tcp`) to `127.0.0.1:<port>` inside the container. |
| Restart | The configured restart command, by default `kill -TERM 1`: SIGTERM to the service, which shuts down gracefully. The container's restart policy must then start it again. HEAppE Management reconnects over SSH and waits until `/health` returns `200`. |
| Machine list | `psql` inside the container, if installed. |

### Properties

- Works without access to Docker or the VM: only an SSH server in the container and a key are needed.
- Machines and notifiers can be managed and the HEAppE instance can be assigned, so the Clusters page works as for
  the other modes.
- The SSH host key is pinned, as in the other SSH mode.

### Downsides

- **An SSH server must run inside the container.** The official QScheduler image does not include one, so a custom
  image is needed. It adds attack surface to the service container, and the private key gives shell access to a
  container that holds the database credentials.
- **Restarting depends on the container setup.**
  - `kill -TERM 1` works only if `qscheduler serve` is PID 1 and the container has a restart policy (for example
    `unless-stopped`). Without a restart policy, the service stays down after the first change.
  - If PID 1 is a process supervisor or the SSH server, the default command restarts the wrong process or stops the
    whole container. Configure a suitable restart command (for example the supervisor's restart command).
  - The SSH server usually restarts with the container, so the SSH connection drops during every restart.
- **Without a restart command, changes wait.** If the restart command is empty, new machines and notifiers are
  written to the database but the instance is marked *restart pending* until someone restarts the container and uses
  **Actions → Confirm manual restart**. New machines are not usable and notifier changes do not apply until then.
- **No Docker control:**
  - no **Update** (the image cannot be changed from inside the container),
  - no Docker health status and no container logs when something fails,
  - no network setup: HEAppE must already reach *Host as seen from HEAppE* and the port, and the callback URL must
    be entered manually,
  - **Undeploy** is not possible, only **Unregister**.
- **DATABASE_URL access:** reading it from `/proc/1/environ` requires the SSH user to be root or the same user as the
  service. Otherwise enter `DATABASE_URL` in the registration form.
- **Machine listing** needs `psql` in the container. Without it, machines are not listed and an existing machine is
  checked only over the REST API.

Prefer **SSH to the VM running the container** whenever the VM is accessible.

---

## When QScheduler is restarted

QScheduler loads machines and notifiers only at startup, so these actions restart it:

| Action | Restart |
|---|---|
| Add quantum machine – *Register new machine* | yes (once, also covers the cluster's notifier) |
| Add quantum machine – *Use existing machine* | only with notifications on (the cluster's notifier is added) |
| Remove quantum machine | when the machine is removed from QScheduler or the cluster had a notifier |
| Assign a HEAppE instance | no (notifiers are created per cluster) |
| Edit notification settings or generate new tokens | yes, once, when the HEAppE instance already has clusters on the QScheduler |
| Unassign a HEAppE instance | only when leftover notifiers of that HEAppE are removed |
| Update, Restart | yes |

A restart is graceful: pending state is written to the database and running backend jobs are re-attached. Requests
arriving during the restart fail, and HEAppE retries status queries later.

---

## Security notes

- SSH private keys, key passphrases and database URLs are stored in the HEAppE Management database in plain text, the
  same way as other instance credentials. They are never sent back to the browser.
- Use a dedicated SSH key per QScheduler instance with the minimum rights needed (Docker access on the VM, or the
  service user in the container).
- Each cluster's notifier token authenticates callbacks from QScheduler to HEAppE for that cluster only. Tokens are
  always stored in HEAppE Vault, never in the cluster configuration or in HEAppE Management. If a token may have
  leaked, edit the assignment and tick *Generate new tokens for all clusters of this HEAppE*.
- HEAppE Vault must be available when clusters are created or their notification settings change.
- *Publish on host* binds to `127.0.0.1` only. Expose QScheduler beyond the host only behind a reverse proxy or
  firewall.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| *No QScheduler instance is assigned to HEAppE instance …* on the Clusters page | Assign the HEAppE instance on the QScheduler page. |
| *QScheduler features require HEAppE 6.6.0 or newer* | Upgrade HEAppE. Also shown when the HEAppE version cannot be read (health API unreachable). |
| No *QScheduler* menu on the Clusters page | The selected HEAppE instance is older than 6.6.0. |
| *HEAppE '…' with the same instance identifier '…' is already assigned* | Two HEAppE instances on one QScheduler need different identifiers (*InstanceIdentifierPath*), because notifier names start with it. |
| *The assignment has notifications on but no callback URL* | Edit the assignment and enter the callback URL. |
| *SSH host key of … changed since registration* | The server was reinstalled or the address points elsewhere. Verify the host, then unregister and register the instance again. |
| *'qscheduler notifier list' failed* during registration | The QScheduler version is older than the notifier release. Update it first. |
| Instance shows *restart pending* | A change was written but the service was not restarted (SSH into container without a restart command). Restart the container, then use **Actions → Confirm manual restart**. |
| Machines: *cannot be listed* | The `postgres:16` image is missing on the instance's Docker host, or `psql` is missing in the container. Only the list is affected. |
| *Assignment saved, but updating the HEAppE clusters failed* | The HEAppE API was unavailable. Open the assignment and save it again. |
| Jobs stay in *Submitted* with notifications on | QScheduler cannot reach the callback URL. Check the callback URL from the QScheduler host, or edit the assignment and turn notifications off (HEAppE then polls). |
| *Removing machine … failed … has N task(s)* | The machine is still in use. Wait, or tick *Force* (deletes its tasks and sessions). |

---

## Action reference

| Where | Action | Available for | Effect |
|---|---|---|---|
| QScheduler page | Deploy New | – | New QScheduler + PostgreSQL on the HEAppE Management Docker host, optional assignment. |
| QScheduler page | Register Existing | – | Adds a running QScheduler (local container, SSH to VM, SSH into container). |
| Instance → Actions | Update | deployed, local, SSH to VM | New image (git build or existing image), container recreated, rollback on failure. |
| Instance → Actions | Restart | all | Graceful restart. SSH into container without a restart command: *Confirm manual restart* (health check only). |
| Instance → Actions | Undeploy | deployed | Removes containers and network, optionally the database volume. Requires no assignments. |
| Instance → Actions | Unregister | local, SSH to VM, SSH into container | Removes the instance from HEAppE Management only. Requires no assignments. |
| Instance card / Actions | Resolve... | missing or unreachable instances | Archive, Restore or Delete with entities. |
| Instance → Actions | Restore... | archived (or missing) instances | Deploys QScheduler again, registers the machines, new notifier and token per cluster, clusters repointed. |
| Instance → Actions | Delete with entities... | archived (or missing) instances | Deletes the clusters and, as selected, their projects, queue groups and Docker leftovers; forgets the instance. |
| Instance → Actions | Unarchive | archived instances whose service answers again | Manages the instance as before; nothing is changed. |
| Instance card | Assign | all | Network access, notifications on/off, callback URL. |
| Instance card → Notifiers | remove (unmanaged) | unmanaged notifiers, not archived | Removes the notifier after a warning and acknowledgment; refused when a cluster of an assigned HEAppE uses it. |
| Assignments table | Edit | all | Change notifications or callback URL, or generate new tokens; recreates the notifiers of existing clusters. |
| Assignments table | Unassign | all | Removes network access and leftover notifiers. Requires no clusters of that HEAppE on the instance. |
| Clusters → QScheduler | Add quantum machine | assigned instances | New or shared machine + HEAppE cluster, queue, queue group, optional project; with notifications on, the cluster's own notifier and token (Vault). |
| Clusters → QScheduler | Remove quantum machine | QScheduler clusters of the current HEAppE | Deletes the cluster and its notifier, optionally removes the machine from QScheduler (`--force` optional). |
| Clusters → QScheduler | Manage QScheduler instances | – | Opens the QScheduler page. |
