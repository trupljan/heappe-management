# QScheduler recovery

HEAppE Management recognises error states of QScheduler instances and of QScheduler clusters in HEAppE, and offers
fixes in the UI. HEAppE Management never resolves them on its own: every fix is started by the admin.

This file is part of the admin panel's recovery documentation: recovery of HEAppE instances is in
[Recovery_README.md](Recovery_README.md). Deploying and using QScheduler is in [QScheduler_README.md](QScheduler_README.md),
including the [Troubleshooting](QScheduler_README.md#troubleshooting) table for errors without a recovery action.

## Contents

- [Overview](#overview)
- [Instance not responding](#instance-not-responding)
- [Instance missing or unreachable](#instance-missing-or-unreachable)
  - [Archive](#archive)
  - [Delete with entities](#delete-with-entities)
  - [Restore](#restore)
- [Cluster checks on the cluster detail page](#cluster-checks-on-the-cluster-detail-page)
  - [Wrong notification settings](#wrong-notification-settings)
  - [Machine missing](#machine-missing)
  - [Instance unknown, archived or unreachable](#instance-unknown-archived-or-unreachable)
- [Admin token missing or rejected](#admin-token-missing-or-rejected)
- [Restart pending](#restart-pending)

---

## Overview

| State | Where it is shown | Fix offered |
|---|---|---|
| Container exists, QScheduler does not answer | Instance card: *not responding* | **Try restart** |
| Container removed, or its host cannot be reached | Instance card: *Missing* / *Unreachable* | **Resolve...**: Archive, Restore, Delete with entities |
| Archived instance answers again | Instance card: *Archived* | **Unarchive** |
| Cluster's notifier or callbacks do not match the assignment | Cluster detail → QScheduler panel | **Recreate notifier** / **Disable callbacks** |
| Cluster's machine does not exist in QScheduler | Cluster detail → QScheduler panel | **Recover machine...** |
| Cluster's QScheduler is unknown, archived or unreachable | Cluster detail → QScheduler panel | **Move to another QScheduler...** |
| Admin token missing, not set in the service, or rejected | Progress dialog, instance card | **Fix admin token...** |
| A change waits for a manual restart | Instance card: *restart pending* | **Confirm manual restart** |

Fixes that are part of a normal action are described with that action in [QScheduler_README.md](QScheduler_README.md):
the rollback of *Update* and of *Migrate to shared database*.

---

## Instance not responding

When the container **still exists** but QScheduler does not answer (stopped, crashed or hanging), the card shows
*not responding* and a **Try restart** button. It runs the normal restart: `docker restart` (which also starts a
stopped container) or the restart command of an "SSH into container" instance (*Confirm manual restart* when it has
none), then waits for `/health`. If the service does not come back, the operation log shows the container's last log
lines.

---

## Instance missing or unreachable

When the QScheduler service disappears behind HEAppE Management's back (container removed by hand, VM reinstalled),
the instance card shows:

- **Missing**: the container no longer exists (deployed, local and "SSH to VM" instances).
- **Unreachable**: it cannot be told whether the container exists (Docker or SSH unavailable; for an "SSH into
  container" instance the SSH login fails, which looks the same as a removed container). Check the host before
  deleting anything.

HEAppE Management never resolves this on its own. **Resolve...** (on the card or in *Actions*) offers three choices:

| Choice | What happens | Undo |
|---|---|---|
| **Archive** | The record, its assignments and all HEAppE clusters are kept **unchanged** (jobs on them fail until QScheduler is back). | *Restore*, or *Unarchive* when the service answers again (e.g. it was only down). |
| **Restore** | Deploys QScheduler again and reassigns everything (see below). | – |
| **Delete with entities** | Deletes what belonged to the instance, as selected (see below), and forgets it. | No. |

### Archive

The card shows *Archived* with the reason; restart, update, assign, unassign and undeploy are disabled, no machine can
be added, and *Remove quantum machine* deletes only the HEAppE cluster without contacting QScheduler.

An archived instance offers **Restore...**, **Delete with entities...** and, once its service answers again,
**Unarchive** (the instance is managed as before; nothing is changed).

### Delete with entities

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

### Restore

Restore deploys QScheduler on the HEAppE Management Docker host the same way as *Deploy New* (instances that were
registered, local or remote, become deployed instances):

- **Image**: the previous branch / tag / image is preselected; any other branch, tag or local image can be chosen.
- **Service**: container name and port (default: the previous ones). When they differ from the old endpoint, the
  clusters and their file transfer methods are pointed to the new one.
- **Database**:
  - *Deploy new PostgreSQL*: a fresh database; old leftovers of the same name (PostgreSQL container, network,
    volume) are removed.
  - *Shared database (new schema)*: a new role and schema in the [shared database](QScheduler_README.md#shared-database).
  - *Reuse the old database* (deployed instances under their original name): the old PostgreSQL container if it
    still exists, the kept volume with the stored password, or the kept schema in the shared database. Machines
    that still exist in it are kept.
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

## Cluster checks on the cluster detail page

The **QScheduler** panel on the cluster detail page of a QScheduler cluster (see
[Cluster detail](QScheduler_README.md#cluster-detail-of-a-qscheduler-cluster)) checks the cluster when the page opens;
the arrow checks again. Its actions need HEAppE 6.6.0+.

### Wrong notification settings

With notifications on for this HEAppE, the cluster must have callbacks enabled,
`QSchedulerNotifier` = `<HEAppE identifier>.<machine>`, a `QSchedulerNotifyToken` (Vault), and that notifier must be
registered in QScheduler with the assignment's callback URL. QScheduler does not expose notifier tokens, so the token
value itself cannot be compared. With notifications off, callbacks must be disabled.

Otherwise the problems are listed with:

- **Recreate notifier** (notifications on): a new notifier with a new token, the cluster's old notifier is removed if
  no other cluster uses it, one QScheduler restart (CLI versions only), the token stored in Vault.
- **Disable callbacks** (notifications off).

### Machine missing

When the cluster's machine (the queue of its node type) does not exist in QScheduler, jobs on the cluster fail and
**Recover machine...** offers:

- *Register a new machine with this name* (backend `test` or `iqm`, queue size, IQM URL, device, token, poll
  interval), or
- *Use an existing machine*: the cluster's queue is switched to it (refused when another cluster of this HEAppE on
  the same QScheduler uses it).

Either way the cluster gets the notifier `<identifier>.<machine>` with a new token (notifications on) and
QScheduler restarts once (CLI versions only).

### Instance unknown, archived or unreachable

**Move to another QScheduler...** is offered when the cluster's QScheduler instance is not registered in HEAppE
Management, is archived, or cannot be reached. The cluster is **not deleted**: its queues, projects, allocations,
credentials and job history stay.

- Choose another instance this HEAppE is assigned to (it must be healthy), and either *use an existing machine* there
  (the cluster's queue is switched to it if the name differs) or *register a new machine* with the cluster's machine
  name.
- The cluster and its file transfer methods are pointed to the new endpoint, it gets the notifier
  `<identifier>.<machine>` there with a new token (Vault), and the new QScheduler restarts once (CLI versions only).
- The old notifier is removed from the old instance only if that one still answers.
- Tasks that were running on the old instance are not moved.
- Refused when another cluster of this HEAppE already uses the machine on the target instance.

---

## Admin token missing or rejected

QScheduler 0.2.1+ is managed through its admin API with the instance's admin token (see
[Admin API and admin token](QScheduler_README.md#admin-api-and-admin-token)). An action fails when:

| Reason | Meaning |
|---|---|
| missing | HEAppE Management has no token stored for the instance, and the container environment does not have one either. |
| not set | The service has no `ADMIN_TOKEN`, so its admin API is disabled (HTTP 403). |
| rejected | The service rejected the stored token (HTTP 401), e.g. it was regenerated by another HEAppE Management. |

The progress dialog and the instance card then offer **Fix admin token...**:

- *Set token*: enter the token, e.g. copied from another HEAppE Management that manages the same QScheduler (*Show*
  there). It is checked against the service when the admin proxy exists.
- *Regenerate* (Docker-based instances): recreates the container with a new token. **Other HEAppE Management instances
  lose admin access until they get the new token.**

---

## Restart pending

An instance reached over SSH into the container **without a restart command** cannot be restarted by HEAppE
Management. After a change that needs a restart (older QScheduler versions, managed with the CLI), the card shows
*restart pending*. Restart the container yourself, then use **Actions → Confirm manual restart**: it checks that
`/health` answers and clears *restart pending*.
