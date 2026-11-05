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
  - [Log level](#log-level)
  - [Undeploy / Unregister](#undeploy--unregister)
- [Assigning HEAppE instances](#assigning-heappe-instances)
  - [Notifications](#notifications)
  - [Edit an assignment](#edit-an-assignment)
  - [Unassign](#unassign)
- [Clusters page: quantum machines](#clusters-page-quantum-machines)
  - [Add a quantum machine](#add-a-quantum-machine)
  - [Remove a quantum machine](#remove-a-quantum-machine)
  - [Suspend / resume a machine](#suspend--resume-a-machine)
- [SSH directly into the QScheduler container (obsolete)](#ssh-directly-into-the-qscheduler-container-obsolete)
- [When QScheduler is restarted](#when-qscheduler-is-restarted)
- [Security notes](#security-notes)
- [QScheduler network and aliases](#qscheduler-network-and-aliases)
- [Troubleshooting](#troubleshooting)
- [Action reference](#action-reference)
- Recovery from error states: [QScheduler_Recovery_README.md](QScheduler_Recovery_README.md)
- Diagram of containers, networks and volumes: [QScheduler_Deployment_Diagram.md](QScheduler_Deployment_Diagram.md)

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
| | *Force a clean rebuild* | Builds with `--no-cache --pull`: every step is run again and newer base images are pulled (slower). Use it when a rebuild with the cache does not pick up a change, e.g. of a dependency or base image. Also in *Update* and *Restore*. |
| | *Image available on this host* | Uses an image that is already on the Docker host (pick from the suggestions or type its name). |
| | Git repository, Branch / tag, Image | Defaults: `https://github.com/It4innovations/qscheduler.git`, `main`, `qscheduler:latest`. |
| | Branch / tag picker | When the repository can be read, *Branch / tag* is a list of its branches (default branch first) and tags (newest first); *Other (type manually)...* allows any other ref. The list is loaded again when the repository URL changes. If the repository cannot be read, the field stays a plain text input. See [Branch / tag list](#branch--tag-list). |
| Service | Name | A prefix of your choice (letters, digits, `_`, `.`, `-`, max 54 characters); a random id is **always appended**: `mydev` becomes e.g. `mydev-5190156f`, empty gives `qscheduler-5190156f`. The result is the instance name, the container name and the host name HEAppE uses; the database container, network and volume are named after it. |
| | Service port | Port of the REST API inside the container (default `4300`). |
| | Publish on host | Optional. Publishes the port on `127.0.0.1` only. |
| | Log level | `error`, `warn`, `info` (default), `debug` or `trace`, set as `RUST_LOG` of the container. Change it later with [Log level](#log-level). |
| | Database | *Shared database (recommended)*: creates the role and schema `qs_<name>` in the [shared database](#shared-database) and the internal network `<name>_db_net`, which the shared database joins; available once the shared database is deployed. *Dedicated PostgreSQL container (experiments)*: creates the container `<name>-pgsql`, the internal network `<name>_db_net` (subnet size chosen in *Database network size*, default `/29`, see [Database networks](#database-networks)) and the volume `<name>-pgdata`. *Use existing database*: enter `DATABASE_URL` (`postgres://...`) and optionally the Docker network on which the database is reachable. |
| QScheduler network and aliases | Subnet, Size | Subnet of the instance's own internal network `<name>_qs_net` (default `/27`). A free subnet of `QSCHEDULER_NETWORK_POOL` is proposed when the dialog opens or the size changes (magic-wand button: propose again); enter another one if it collides with your LAN or VPN. An entered subnet is checked at once: when it overlaps an existing Docker network, a free one of the same size is offered. See [QScheduler network and aliases](#qscheduler-network-and-aliases). |
| | Aliases | Optional, comma separated host names, e.g. `vlq.machine.qscheduler.it4i.cz` (any valid DNS name of your site; restricted to a zone only when `QSCHEDULER_ALIAS_ZONE` is set). HEAppE clusters can use them instead of the container name. |
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
| **Remote: SSH to the VM running the container** *(obsolete)* | SSH to the VM, then `docker exec <container> qscheduler ...` there | QScheduler in Docker on another machine. |
| **Remote: SSH directly into the QScheduler container** *(obsolete)* | SSH into the container (it must run an SSH server), then `qscheduler ...` | Docker on the remote machine is not accessible. **Limited management**, see [below](#ssh-directly-into-the-qscheduler-container-obsolete). |

> **SSH management is obsolete.** Manage machines and notifiers through the
> [admin API](#admin-api-and-admin-token) wherever possible (QScheduler 0.2.1+), for local and remote instances alike.
> Use the SSH modes only for what the admin API cannot do: QScheduler older than 0.2.1, or Docker operations (*Update*,
> *Restart*) on a remote host. Do not use them for new setups.

Fields:

| Field | Modes | Description |
|---|---|---|
| SSH host, SSH port, SSH user | both SSH modes | SSH port defaults to `22`. |
| SSH private key | both SSH modes | Paste the key or load it from a file. Ed25519, ECDSA and RSA keys in OpenSSH or PEM format are supported. |
| Key passphrase | both SSH modes | Only for an encrypted key. |
| Container | local, SSH to VM | Name of the QScheduler container. For the local mode the page suggests containers that run `qscheduler serve`. |
| Docker command | SSH to VM | `docker`, or `sudo -n docker` when the SSH user needs passwordless sudo for Docker. |
| DATABASE_URL | SSH into container | Optional. By default it is read from the environment of the service process (PID 1) in the container. |
| Restart command | SSH into container | Default `kill -TERM 1`. Leave empty to restart manually. See [below](#ssh-directly-into-the-qscheduler-container-obsolete). |
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
  instance, reusing Docker's build cache; tick *Force a clean rebuild* to build without the cache and pull newer base
  images.
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

### Log level

**Actions → Log level...** (Docker-based instances: deployed, local container, SSH to VM). Sets `RUST_LOG` of the
QScheduler container:

| Level | Logs |
|---|---|
| `error` | errors only |
| `warn` | also warnings |
| `info` | default |
| `debug` | detailed, for troubleshooting |
| `trace` | everything (very verbose) |
| *Custom filter* | any `RUST_LOG` filter, e.g. `info,qscheduler=debug,hyper=warn` (letters, digits and `_ : = , . -`, at most 200 characters) |

QScheduler reads the level only at startup, so the container is **recreated** with the same image and settings, as in
*Update*: requests fail for a few seconds, running work is persisted and re-attached, and the previous container is
restored if the new one does not become healthy. The level is kept by *Update*, *Regenerate token*, extra hosts and
*Restore*. The dialog shows the level the container runs with; the instance card shows the level last set here. Use
`debug` and `trace` only temporarily. Over SSH into the container, set `RUST_LOG` in the service yourself.

### Undeploy / Unregister

Refused while any HEAppE instance is assigned. [Unassign](#unassign) them first.

- **Undeploy** (instances deployed by HEAppE Management): removes the QScheduler container, its PostgreSQL container
  and database network. The database volume is removed only when *Also delete the database volume* is ticked. The
  image is kept. With the shared database: the shared database is disconnected from the instance's network, and its
  schema and role are dropped when *Also drop its schema and role* is ticked (the default).
- **Unregister** (registered instances): removes the instance from HEAppE Management only. The QScheduler service
  keeps running.

### Instance not responding, missing or unreachable

When the QScheduler service stops answering or disappears behind HEAppE Management's back, the instance card shows
*not responding*, *Missing* or *Unreachable* and offers **Try restart** or **Resolve...** (Archive, Restore, Delete
with entities). See [QScheduler recovery](QScheduler_Recovery_README.md#instance-not-responding).

---

## Assigning HEAppE instances

**Assign** on an instance card. A HEAppE instance must be assigned before its Clusters page can add machines from
that QScheduler. Only HEAppE **6.6.0 or newer** can be assigned; the dialog shows the version of the selected
instance and disables *Save* for older ones.

What an assignment does:

1. **Network** (QScheduler on the HEAppE Management Docker host): the `heappe` container joins the instance's
   [QScheduler network](#qscheduler-network-and-aliases), live and in its `docker-compose.override.yml`; HEAppE is not
   restarted. Instances not migrated yet: the QScheduler container joins the Docker network of the HEAppE API container
   instead, and the HEAppE API is restarted briefly the first time. A remote QScheduler must already be reachable from
   HEAppE at *Host as seen from HEAppE* and the service port.
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
| | Machine name | Up to 30 characters (letters, digits, `_`, `.`, `-`). Becomes the HEAppE queue. With *Use existing machine*, a dropdown lists the machines registered in the selected instance (with their backend); *Other (type manually)...* or an instance whose machines cannot be listed falls back to a text field. For a new machine, registered names are suggested. |
| | Backend | `test` (in-process simulator) or `iqm`. For `iqm`: server URL, device name (for example `star24`), token and poll interval (for example `500ms`). |
| | Machine limits | Queue size (`4`), max session time (`2h`), default task time limit (`1h`), limit check interval (`2s`), max clock skew (`4s`). Durations need a unit. |
| HEAppE cluster | Cluster name | Always the machine name (read-only): HEAppE uses the cluster name as the QScheduler machine, so a cluster named differently fails its jobs. Refused when this HEAppE already has a cluster of that name. |
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

The cluster detail page shows a **QScheduler cluster** badge next to *Cluster Configuration*, and a **QScheduler**
panel at the top of it (checked when the page opens; the arrow checks again):

- **Attached to**: the QScheduler instance the cluster points to (`QSchedulerHost` / `MasterNodeName` + port), with a
  link to the QScheduler page, and the cluster's machine. Endpoints that are not a registered instance, archived
  instances and instances this HEAppE is not assigned to are reported and nothing else is checked.
- **Notifications**: whether the cluster's notifier and callbacks match the assignment.
- **Machine**: whether the cluster's machine (the queue of its node type) exists in QScheduler.
- **Cluster name**: whether it equals the machine name. HEAppE uses the cluster name as the QScheduler machine, so a
  cluster named differently (e.g. created before this check, or renamed by hand) fails its jobs. **Rename cluster to
  &lt;machine&gt;** fixes it; queues, projects, settings, Vault values and job history are kept. The dashboard's Quantum
  Machines card flags such clusters too. *Recover machine* and *Move* with another machine rename the cluster as well.

When a check fails, the panel offers **Rename cluster**, **Recreate notifier** / **Disable callbacks**, **Recover
machine...** or **Move to another QScheduler...**. See [Cluster checks](QScheduler_Recovery_README.md#cluster-checks-on-the-cluster-detail-page).

The panel needs HEAppE 6.6.0+ for its actions. Its *Webhook & Callback
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

### Suspend / resume a machine

Stops a machine from taking new work without removing anything, e.g. during calibration or maintenance. Needs
QScheduler **0.2.1 or newer** (admin API); the HEAppE instance must be assigned to the QScheduler.

Where:

- **Dashboard → Quantum Machines**: one row per QScheduler cluster of the current HEAppE instance with its machine,
  QScheduler instance and state, and **Suspend** / **Resume**. The card is hidden when the HEAppE instance is not
  assigned to any QScheduler.
- **Cluster detail → QScheduler panel**: the machine's state and **Suspend machine...** / **Resume machine...**.

| State | Meaning |
|---|---|
| Online | Registered, not suspended, its backend answers (`GET /machine/{name}/about`). |
| Backend offline | Registered and not suspended, but the backend (e.g. IQM) does not answer. |
| Suspended | New tasks and sessions are rejected; the reason and the time are shown. |
| Not registered | The machine does not exist in QScheduler (see *Recover machine...* on the cluster detail). |
| Unknown | QScheduler cannot be asked (not running, admin token, older than 0.2.1) or is not registered here. |

**Suspend** asks for a reason (shown to users whose jobs are rejected, at most 512 characters) and what happens to
the work already on the machine:

| Option | Effect |
|---|---|
| Let it finish (default) | Queued and running tasks and open sessions continue. |
| Cancel waiting work | Tasks not yet sent to the backend fail, all sessions close; running tasks continue. |
| Cancel everything | Running tasks fail too, and their cancellation is requested from the backend. |

While suspended, QScheduler answers every new task and session on the machine with HTTP `409` and the reason, also
tasks submitted into an already open session. The suspension stays in place after a QScheduler restart. **Resume**
lets the machine accept new work again; work failed or closed by the suspension stays so.

**The suspension belongs to the machine, not to the cluster.** Before the dialog can be confirmed, HEAppE Management
asks every HEAppE instance assigned to the QScheduler which of its clusters use the machine. When another cluster uses
it, or an assigned HEAppE instance cannot be asked, the dialog lists them and the action needs the confirmation
*I understand that ... affects all these clusters*. The server refuses an unconfirmed action on a shared machine.

---

## SSH directly into the QScheduler container (obsolete)

> **Obsolete.** Like *SSH to the VM*, this mode is kept only for existing setups. Manage machines and notifiers through
> the [admin API](#admin-api-and-admin-token) instead.

Use this mode only when the Docker host of a remote QScheduler cannot be accessed. HEAppE Management then talks only
to a shell inside the QScheduler container. Wherever such an instance is involved, the page shows a yellow
**SSH into container – Limited management** warning.

### How it works

| Task | How it is done |
|---|---|
| Machines and notifiers, QScheduler 0.2.1+ | Admin API over HTTP through the admin proxy (see [Admin API and admin token](#admin-api-and-admin-token)), not over SSH. |
| Machines and notifiers, older versions | `qscheduler ...` in the container, with `DATABASE_URL` from the registration form or from the environment of PID 1 (`/proc/1/environ`). |
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

Prefer the [admin API](#admin-api-and-admin-token) for machines and notifiers. If SSH is still needed, *SSH to the VM
running the container* (also obsolete) gives more control than this mode.

---

## When QScheduler is restarted

**QScheduler 0.2.1 and newer** is managed only over its admin API (see
[Admin API and admin token](#admin-api-and-admin-token)): machines and notifiers are added and removed in the running
service, and **none of the actions below restarts QScheduler** (only *Update*, *Restart* and *Regenerate token* do).
There is no CLI fallback for these versions: a missing or rejected admin token stops the action.

Older versions (CLI) load machines and notifiers only at startup, so these actions restart them:

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

## Shared database

One PostgreSQL server for all QScheduler instances on the HEAppE Management Docker host. Each instance gets its own
role and schema; a dedicated PostgreSQL container per instance stays available for experiments.

**Deploy shared database** (card at the top of the QScheduler page):

- container `qscheduler-shared-pgsql` (`postgres:16`, setting or environment variable `QSCHEDULER_SHARED_DB_IMAGE`),
  volume `qscheduler-shared-pgdata`, database `qscheduler`, internal network `qscheduler-shared-db_net`;
- no published port; the backup directory is mounted at `/backups`;
- the admin password is generated and stored encrypted; `public` schema and database access are revoked from all
  roles.

**Per instance**: role and schema `qs_<instance name>` (lowercase, other characters replaced by `_`), the role's
`search_path` set to the schema and `CONNECT` on the database only. QScheduler's migrations then create its tables in
that schema. The shared database joins the instance's internal `<name>_db_net`, so each instance reaches it only
through its own network, and roles cannot read other schemas. Verified with QScheduler 0.2.1 and PostgreSQL 16.

The card shows the state, the PostgreSQL version and the schemas with size, instance and open connections:

- **Update image**: only within the same PostgreSQL major version. The container is recreated on the same volume, and
  instances lose the database for a few seconds.
- **Remove**: only when no instance uses the shared database; optionally deletes the volume.
- **drop**: removes a schema that no instance uses, e.g. one left by *Restore* under another name.

**Instance → Actions → Migrate to shared database...** (deployed instances with a dedicated PostgreSQL container, once
the shared database exists):

1. QScheduler is stopped for a consistent copy. Requests fail meanwhile; running backend work is re-attached
   afterwards, as after a restart.
2. A backup of the old database is written (it stays in the instance's backups).
3. The dump is restored as the new role into a temporary database. There its `public` schema is renamed to
   `qs_<name>`, then it is copied into the shared database. The row counts of every table are compared with the
   old database.
4. The QScheduler container is recreated with the new `DATABASE_URL`; everything else (token, networks, extra hosts)
   is kept.

On any failure the schema, role and temporary database are dropped and QScheduler starts again on the old database.
The old PostgreSQL container and volume are kept (stopped) unless *Remove the old PostgreSQL container and volume* is
ticked.

## Backups

**Instance → Actions → Backups...** (instances deployed by HEAppE Management, shared or dedicated database) lists the
dumps of the instance and offers **Backup now** and delete.

- **Location**: `<QSCHEDULER_BACKUP_DIR>/<instance>/<UTC time>_<QScheduler version>.dump`. `QSCHEDULER_BACKUP_DIR` is
  a setting or environment variable, default `/opt/heappe-deployment/qscheduler-backups`, on the host.
- **Format**: `pg_dump` custom format. Each dump is checked with `pg_restore --list`; a dump without tables is
  refused and removed.
- **How**:
  - shared database: `pg_dump -n <schema>` in the shared container;
  - dedicated database: `pg_dump` in `<name>-pgsql`, copied to the host with `docker cp`.
- **Restore** (`pg_restore --clean --if-exists`) is used by the in-place update's rollback (coming next).

## Admin API and admin token

QScheduler 0.2.1+ protects its admin endpoints (`/machines`, `/machine/{name}`, `/notifiers`, `/notifiers/{name}`)
with the `ADMIN_TOKEN` of the service (Bearer token; unset → `403`, wrong → `401`). HEAppE Management calls them only
over HTTP, through an **admin proxy**; it runs no `qscheduler` CLI and no command inside the container for them.

**Admin proxy.** One `nginx` container per QScheduler instance, `<name>-admin-proxy`, on the Docker host of HEAppE
Management:

- it forwards to `<Host as seen from HEAppE>:<port>`:
  - **local instances**: it joins the instance's [QScheduler network](#qscheduler-network-and-aliases), so it works
    before any HEAppE instance is assigned,
  - **remote instances**: it joins the HEAppE network of every assigned HEAppE instance and reaches QScheduler through
    the tunnel that connects its Docker network to the local HEAppE network,
- it is also on Docker's default `bridge`: a container only on internal networks cannot publish a port,
- it forwards only the admin endpoints and the machine state endpoints (`/machine/{name}/suspension`,
  `/machine/{name}/suspensions`, `/machine/{name}/about`); every other path returns `404`. A proxy created with an
  older set of routes is recreated on its next use,
- it is published on `127.0.0.1` only (random port, shown on the instance card), i.e. for HEAppE Management,
- it is created on the first admin call, follows assignment changes, is recreated when the endpoint, image or network
  layout changes (e.g. after *Restore*), and is removed with *Undeploy* / *Unregister* or *Delete with entities*, and
  for a remote instance also with its last assignment.

A remote QScheduler 0.2.1+ without an assignment has no proxy, so its machines and notifiers are not listed.
The image is `nginx:1.27-alpine` (setting or environment variable `QSCHEDULER_ADMIN_PROXY_IMAGE`).

**Admin token.** Stored encrypted on the instance record (key derived from Django `SECRET_KEY`).

- *Deploy* and *Restore* generate it; *Update* adds one to a container that has none.
- *Register existing*: enter it in **Admin token**, or leave it empty to take it from the container environment
  (not possible over SSH into the container). A Docker-based instance without a stored token also takes it from the
  container environment on first use.
- **Actions → Admin token...**: *Show* (to use it in another HEAppE Management that manages the same QScheduler),
  *Set token* (checked against the service when the proxy exists), *Regenerate* (Docker-based instances: recreates the
  container with a new token; **other HEAppE Management instances lose admin access until they get the new token**).
- When an action fails because the token is missing or rejected, the progress dialog and the instance card offer
  **Fix admin token...** (see [QScheduler recovery](QScheduler_Recovery_README.md#admin-token-missing-or-rejected)).

---

## QScheduler network and aliases

Every QScheduler instance on the HEAppE Management Docker host (deployed or an existing local container) has its own
internal network `<name>_qs_net`:

| Address | Used by |
|---|---|
| `.1` | gateway |
| `.2` | **QScheduler, static**: kept by *Update*, *Regenerate token*, *Migrate to shared database*, extra hosts and Docker restarts |
| lower half | reserved for static addresses |
| upper half (`--ip-range`) | dynamic addresses: the HEAppE containers and the admin proxy, so none of them can take `.2` while QScheduler is recreated |

- The **`heappe` container of every assigned HEAppE instance joins it**: live (`docker network connect`, no HEAppE
  restart) and in that instance's `docker-compose.override.yml`, so a compose recreate (Extra Hosts, OpenTelemetry,
  regenerate configs) keeps it. *Unassign* removes it from both. `datastagingapi` does not join: it rejects QScheduler
  jobs.
- QScheduler no longer joins the HEAppE networks; it keeps the default `bridge` for egress (e.g. to IQM) and its
  database network.
- HEAppE reaches QScheduler by container name or alias, resolved by Docker's DNS on that network. The instance card
  shows the network, subnet and static address.
- The **admin proxy** joins this network (and Docker's `bridge`, which it needs to publish its port on `127.0.0.1`), so
  machines and notifiers can be managed before any HEAppE instance is assigned.
- *Undeploy*, *Unregister* and *Delete with entities* remove the network; *Restore* reuses it when it still exists
  (same subnet and address), otherwise it creates one with the subnet entered in the restore dialog.

**Aliases** are host names such as `vlq.machine.qscheduler.it4i.cz`: any valid DNS name (each provider can use its own
domain), unique on this host (not used as alias, service host or container name by another instance). Setting
`QSCHEDULER_ALIAS_ZONE` restricts them to one zone.

- set when deploying, changed later with **Actions → Aliases...**;
- local instances: Docker network aliases on `<name>_qs_net`. Docker cannot change the aliases of a connected
  container, so a change reconnects QScheduler to the network, which interrupts it for well under a second for the
  HEAppE instances on it. The aliases are checked from every assigned HEAppE container afterwards. An alias that a
  HEAppE cluster still uses cannot be removed;
- remote instances: only stored. Add each alias with the QScheduler's IP as an extra host of the HEAppE instance
  (*Containers & Services → Extra Hosts*); this is manual for now and will be automated with the tunnel to the remote
  site. The same applies when the HEAppE instance itself is not on this host (the assignment row says so);
- **Add quantum machine → Host name** picks the container name or an alias as the cluster's `MasterNodeName` (also
  `QSchedulerHost` and the file transfer method's host). One cluster per alias. *Restore* keeps the alias of such
  clusters.
- The Extra Hosts tab of a HEAppE instance lists the aliases of its QScheduler instances and how each is resolved:
  *Docker DNS*, *not applied* (instance without a QScheduler network) or *manual · to be automated* with the extra host
  found, or an **Add extra host** button that adds the row to HEAppE API.

**Migrate to QScheduler network...** (*Actions*, or the link on the card) moves an existing local instance that has
none yet, without downtime:

1. creates `<name>_qs_net` (subnet proposed or entered) and connects QScheduler with its static address and aliases;
2. the `heappe` container of every assigned HEAppE instance joins it (live and in its override file) and must reach
   QScheduler there (`GET /health`);
3. only then QScheduler leaves the HEAppE networks it had joined for the assignments, and the admin proxy is recreated
   on the new network.

The clusters keep their host name (the container name resolves on the new network too). If step 1 or 2 fails,
everything is rolled back and the old networks are untouched.

| Variable | Default | Description |
|---|---|---|
| `QSCHEDULER_ALIAS_ZONE` | *(unset)* | Optional DNS zone the aliases must be in, e.g. `machine.qscheduler.it4i.cz`. Unset: any valid host name. |
| `QSCHEDULER_NETWORK_POOL` | `10.213.0.0/16` | Private range the subnets are proposed from (shared with the database networks). |

## Database networks

Internal database networks (`<name>_db_net`, also when Restore recreates one) get an explicit small subnet instead of
one from Docker's default address pools, which hand out `/16` or `/20` subnets and fail with *all predefined address
pools have been fully subnetted* on hosts with many networks. The size is chosen in *Deploy New* and *Restore*
(**Database network size**, shown with *Deploy new PostgreSQL*):

| Size | Usable addresses |
|---|---|
| `/24` | 254 |
| `/25` | 126 |
| `/26` | 62 |
| `/27` | 30 |
| `/28` | 14 |
| `/29` (default) | 6 |

Only QScheduler and its PostgreSQL use the network, so the default `/29` (6 addresses) is enough; a larger size is only
needed if you attach more containers to it yourself.
The first subnet of that size in `10.213.0.0/16` not used by any existing Docker network is taken; if Docker reports
an overlap (a network created meanwhile), the next one is tried.

Change the range or size with environment variables of HEAppE Management, e.g. when `10.213.0.0/16` is used by your
LAN or VPN:

| Variable | Default | Description |
|---|---|---|
| `QSCHEDULER_NETWORK_POOL` | `10.213.0.0/16` | Private range the subnets are taken from. |
| `QSCHEDULER_NETWORK_PREFIX` | `29` | Default of *Database network size* (`/24`–`/29`). |

HEAppE Management creates the database networks and the [QScheduler networks](#qscheduler-network-and-aliases).
QScheduler also joins the default `bridge` network (egress, e.g. to IQM). Instances not migrated to a QScheduler network
yet still join the networks of the HEAppE instances assigned to them.

## Security notes

- SSH private keys, key passphrases, database URLs and admin tokens are stored **encrypted** in the HEAppE Management
  database (Fernet: AES-128 with a random IV per value, plus HMAC), with a key derived from Django `SECRET_KEY`. A
  database dump or backup alone does not reveal them; the database together with `SECRET_KEY` does. If `SECRET_KEY`
  changes, the stored values can no longer be decrypted and must be entered again. They are never sent back to the
  browser. Upgrading runs migration `0012`, which encrypts existing values and drops the plain-text columns.
- Avoid the obsolete SSH modes: the admin API needs only the admin token, while an SSH key gives shell access. If SSH
  is still used, use a dedicated key per QScheduler instance with the minimum rights needed (Docker access on the VM,
  or the service user in the container).
- Each cluster's notifier token authenticates callbacks from QScheduler to HEAppE for that cluster only. Tokens are
  always stored in HEAppE Vault, never in the cluster configuration or in HEAppE Management. If a token may have
  leaked, edit the assignment and tick *Generate new tokens for all clusters of this HEAppE*.
- HEAppE Vault must be available when clusters are created or their notification settings change.
- *Publish on host* binds to `127.0.0.1` only. Expose QScheduler beyond the host only behind a reverse proxy or
  firewall.

---

## Troubleshooting

Error states with a fix in the UI (not responding, missing or unreachable instances, broken clusters, admin token,
restart pending) are described in [QScheduler_Recovery_README.md](QScheduler_Recovery_README.md).

| Symptom | Cause / fix |
|---|---|
| *No QScheduler instance is assigned to HEAppE instance …* on the Clusters page | Assign the HEAppE instance on the QScheduler page. |
| *QScheduler features require HEAppE 6.6.0 or newer* | Upgrade HEAppE. Also shown when the HEAppE version cannot be read (health API unreachable). |
| No *QScheduler* menu on the Clusters page | The selected HEAppE instance is older than 6.6.0. |
| *HEAppE '…' with the same instance identifier '…' is already assigned* | Two HEAppE instances on one QScheduler need different identifiers (*InstanceIdentifierPath*), because notifier names start with it. |
| *The assignment has notifications on but no callback URL* | Edit the assignment and enter the callback URL. |
| *SSH host key of … changed since registration* | The server was reinstalled or the address points elsewhere. Verify the host, then unregister and register the instance again. |
| *'qscheduler notifier list' failed* during registration | The QScheduler version is older than the notifier release. Update it first. |
| Instance shows *restart pending* | A change was written but the service was not restarted (SSH into container without a restart command). Restart the container, then use **Actions → Confirm manual restart** (see [Restart pending](QScheduler_Recovery_README.md#restart-pending)). |
| Machines: *cannot be listed* | The `postgres:16` image is missing on the instance's Docker host, or `psql` is missing in the container. Only the list is affected. |
| *Assignment saved, but updating the HEAppE clusters failed* | The HEAppE API was unavailable. Open the assignment and save it again. |
| Jobs stay in *Submitted* with notifications on | QScheduler cannot reach the callback URL. Check the callback URL from the QScheduler host, or edit the assignment and turn notifications off (HEAppE then polls). |
| *Removing machine … failed … has N task(s)* | The machine is still in use. Wait, or tick *Force* (deletes its tasks and sessions). |

---

## Action reference

| Where | Action | Available for | Effect |
|---|---|---|---|
| QScheduler page | Deploy New | – | New QScheduler + PostgreSQL on the HEAppE Management Docker host, optional assignment. |
| QScheduler page | Register Existing | – | Adds a running QScheduler (local container; SSH to VM and SSH into container are obsolete). |
| QScheduler page → Shared database | Deploy / Update image / Remove / drop schema | – | Shared PostgreSQL for all instances on this host (see [Shared database](#shared-database)). |
| Instance → Actions | Migrate to shared database... | deployed with a dedicated database | Copies the data into a new schema of the shared database (checked row counts) and switches QScheduler to it; old container kept stopped or removed. |
| Instance → Actions | Migrate to QScheduler network... | local instances without a QScheduler network | Own internal network with a static address; HEAppE containers join it, then QScheduler leaves the HEAppE networks (no downtime, rolled back on failure). |
| Instance → Actions | Aliases... | not archived (local: with a QScheduler network) | Sets the instance's aliases; local instances are reconnected to their QScheduler network. |
| Instance → Actions | Backups... | deployed (shared or dedicated database) | List, create and delete database dumps (see [Backups](#backups)). |
| Instance → Actions | Update | deployed, local, SSH to VM | New image (git build or existing image), container recreated, rollback on failure. |
| Instance → Actions | Log level... | deployed, local, SSH to VM | Sets `RUST_LOG` (preset or custom filter); container recreated, rollback on failure. |
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
| Dashboard → Quantum Machines, Cluster detail → QScheduler | Suspend / Resume | QScheduler clusters of the current HEAppE (QScheduler 0.2.1+) | Suspends the cluster's machine (new work rejected, existing work kept or cancelled) or resumes it; a machine shared with other clusters needs a confirmation. |
| Clusters → QScheduler | Manage QScheduler instances | – | Opens the QScheduler page. |
| Cluster detail → QScheduler | Recreate notifier / Disable callbacks | QScheduler clusters with wrong notification settings | New notifier and token for the cluster (or callbacks off), one restart. |
| Cluster detail → QScheduler | Recover machine... | QScheduler clusters whose machine is missing | Registers the machine again or switches the cluster to an existing machine; new notifier and token. |
| Cluster detail → QScheduler | Move to another QScheduler... | clusters whose instance is unknown, archived or unreachable | Keeps the cluster and points it to another assigned, healthy instance (new or existing machine, new notifier and token). |
