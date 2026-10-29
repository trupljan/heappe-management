# QScheduler part (a): shared database, QScheduler network, aliases, redirect, in-place update

**Status:**

| Step | Area | State |
|---|---|---|
| 1 | Shared database and backups | done |
| 2 | QScheduler network, static IP, migration | next |
| 3 | Aliases | planned |
| 4 | In-place update | planned |
| 5 | Redirect | planned |

Undeploy drops the schema by default. The QScheduler network subnet is proposed automatically; the user confirms it
or enters another one (also after a failure).

Scope: one Docker host (the host of HEAppE Management). Remote sites (WireGuard, reverse proxy) are part (b),
remote HEAppE is part (c).

## Decisions

| Topic | Decision |
|---|---|
| Database | One shared PostgreSQL per Docker host, deployed by an explicit action. Each QScheduler instance gets its own role and schema (`search_path`). A dedicated PostgreSQL container per instance stays available for experiments. |
| Isolation | One QScheduler network per QScheduler instance; only the HEAppE instances assigned to it join it. |
| Addressing | Static IP of the QScheduler container in its QScheduler network; subnet entered by hand or allocated from the pool. |
| Names | Docker network aliases (no DNS server). One cluster per alias per site; aliases in a configured zone, e.g. `*.machine.qscheduler.it4i.cz`. |
| Updates | In place (same container name, IP, aliases, token): drain, backup, replace, verify, resume; rollback restores the backup. |
| Redirect | Two steps: drain the machine, then switch the alias to another (assigned) instance and machine; "Switch back" kept. |
| Backups | Host directory, default `/opt/heappe-deployment/qscheduler-backups/<instance>/<timestamp>.dump`. |

Verified with QScheduler built from tag `v0.2.1` and PostgreSQL 16: migrations create their 7 tables and
`_sqlx_migrations` in the role's schema, need no extensions or superuser rights, roles cannot read each other's
schemas, `pg_dump -Fc -n <schema>` / `pg_restore --clean --if-exists -n <schema>` restore machines, tasks (same IDs)
and projects.

---

## 1. Shared database

### Model
`QSchedulerDatabase` (one per Docker host; part (a): the local host):

- `name` (`qscheduler-shared-pgsql`), `image` (`postgres:16`), `volume` (`qscheduler-shared-pgdata`),
  `database` (`qscheduler`), `admin_password_encrypted`, `home_network`, `backup_dir`, `created_at`.

`QSchedulerInstance` gets:

- `db_kind`: `dedicated` (own container, today's "new"), `shared`, `external` (URL entered),
- `db_schema` (= role name), `shared_database` (FK, null unless shared).

### Action "Deploy shared database" (QScheduler page)
1. Volume `qscheduler-shared-pgdata`, home network `qscheduler-shared-db_net` (internal, /29).
2. `docker run -d --name qscheduler-shared-pgsql --restart unless-stopped --network qscheduler-shared-db_net
   -v qscheduler-shared-pgdata:/var/lib/postgresql/data -v <backup dir>:/backups -e POSTGRES_PASSWORD=<generated>
   -e POSTGRES_DB=qscheduler --shm-size 256m postgres:16` - no published port.
3. Hardening: `REVOKE ALL ON SCHEMA public FROM PUBLIC; REVOKE CONNECT ON DATABASE qscheduler FROM PUBLIC;`
4. Admin SQL always runs with `docker exec … psql` (no network access needed for HEAppE Management).

### Deploy a QScheduler instance with `db_mode = shared`
1. Role and schema name: `qs_` + instance name, lowercase, non `[a-z0-9_]` replaced by `_`, max 63 chars, unique.
2. As admin:
   ```sql
   CREATE ROLE qs_x LOGIN PASSWORD '<generated>';
   CREATE SCHEMA qs_x AUTHORIZATION qs_x;
   ALTER ROLE qs_x SET search_path = qs_x;
   GRANT CONNECT ON DATABASE qscheduler TO qs_x;
   ```
3. The instance's internal DB network `<name>_db_net` (as today); the shared DB container joins it with alias
   `qscheduler-shared-pgsql`. Each instance reaches the database only through its own network.
4. `DATABASE_URL=postgres://qs_x:<pw>@qscheduler-shared-pgsql:5432/qscheduler`.

### Undeploy / unregister
- Disconnect the shared DB container from `<name>_db_net`, remove the network.
- "Remove data": `DROP SCHEMA qs_x CASCADE; DROP OWNED BY qs_x; DROP ROLE qs_x;` Otherwise keep schema and role
  (Restore can reuse them).

### Restore (recovery)
- `reuse` for a shared instance: schema still there → new `<name>_db_net`, reconnect the shared DB, same role.

### Shared database card (QScheduler page)
- Health, PostgreSQL version, schemas with size and instance, connections.
- **Update image** (same major version only: recreate with the same volume; major upgrades are out of scope).
- **Remove**: only when no schema belongs to a registered instance.

---

## 2. Backups

- Directory: setting `QSCHEDULER_BACKUP_DIR` (default `/opt/heappe-deployment/qscheduler-backups`), per instance.
- Shared: `docker exec qscheduler-shared-pgsql pg_dump -U postgres -d qscheduler -Fc -n qs_x -f /backups/<instance>/<ts>.dump`.
- Dedicated: one-off `docker run --rm --network <name>_db_net -v <dir>:/backups postgres:16 pg_dump …`
  (existing containers need no new mount).
- Every dump is checked with `pg_restore --list`.
- Restore: `pg_restore --clean --if-exists -n qs_x` (shared) / `--clean --if-exists` (dedicated).
- UI: list backups of an instance (time, size, QScheduler version at backup time), **Backup now**, delete.

---

## 3. QScheduler network and static IP

- Per instance: `<name>_qs_net`, bridge, `--internal` (QScheduler's egress stays on the default bridge), subnet entered
  by hand or the next free /28 from `QSCHEDULER_NETWORK_POOL`. A /28 leaves 13 addresses: QScheduler (`.2`, static),
  admin proxy, part-(b) reverse proxy, and the `heappe` container of each assigned HEAppE (up to 10 HEAppE instances).
  `datastagingapi` does not join: it rejects QScheduler jobs and clusters (`CheckJobNotQScheduler`).
- **Assign**: the `heappe` container of the HEAppE instance joins `<name>_qs_net`
  - live with `docker network connect` (no downtime), and
  - persisted in the instance's `docker-compose.override.yml` (`networks: <name>_qs_net: external: true`), so a
    compose recreate (OpenTelemetry toggle, extra hosts, regenerate configs) keeps it.
- **Unassign**: disconnect it and remove the override entry.
- The QScheduler container no longer joins HEAppE's own networks; HEAppE reaches it by container name or alias on
  `<name>_qs_net`.
- Admin proxy: joins only `<name>_qs_net` (one network instead of one per assignment).
- `recreate_args_from_inspect` keeps static IPs (`--ip` from `IPAMConfig`) and aliases for every network
  (today the IP is not kept).

### Action "Migrate to QScheduler network" (existing instances)
1. Create `<name>_qs_net`; connect QScheduler with `--ip` and its aliases.
2. Connect the `heappe` container of each assigned HEAppE instance (live + override).
3. Check from each HEAppE container: `GET http://<service_host>:<port>/health`.
4. Disconnect QScheduler from the HEAppE networks.

The cluster's `MasterNodeName` (container name) resolves on the new network, so clusters are not changed and there is
no downtime.

---

## 4. Aliases

### Model
`QSchedulerClusterAlias`: `heappe_instance`, `cluster_id`, `alias`, `qscheduler`, `machine`,
`previous_qscheduler`, `previous_machine`, `state` (`active`, `draining`), `updated_at`.

### Rules
- Must be inside `QSCHEDULER_ALIAS_ZONE` (default `machine.qscheduler.it4i.cz`), valid DNS labels, ≤ 253 chars.
- Unique per site (all aliases on this Docker host).

### Setting an alias
- **Add quantum machine**: optional *Alias*. The cluster gets `MasterNodeName = QSchedulerHost = alias`; its file
  transfer method gets `ServerHostname = alias`.
- **Existing cluster** → *Set alias* (cluster detail): same, with cluster PUT and file transfer method repoint.

### Applying aliases
- Docker cannot change the aliases of a connected container. The QScheduler container is reconnected to
  `<name>_qs_net` with `--ip <static>` and all its aliases.
- This is a sub-second interruption on that network only, i.e. for the HEAppE instances assigned to that QScheduler.

### Lookup
- `_instance_of_cluster`: alias table first, then host and port (clusters without an alias).
- Deleting a cluster removes its alias.

---

## 5. Redirect (cluster → another instance and/or machine)

### Step 1 · Drain
- `POST /machine/{m}/suspension` with `cancel = none`; or *force* `cancel = all`, with a warning that running tasks
  fail and are charged their estimated time.
- If the machine is shared, list the other clusters (all assigned HEAppE instances) and require extra confirmation.
- Idle check for every cluster on the machine:
  - HEAppE `ListDetailedJobsForAdmin` (`clusterId`, non-terminal states),
  - `ListSessions` (`clusterId`, `state=Open`).
- Abort: `DELETE` the suspension.

### Step 2 · Switch
Preconditions: the target instance is assigned to the HEAppE instance and the target machine exists.

1. Move the alias:
   - old QScheduler reconnected without it,
   - target QScheduler reconnected with it, on its own `<target>_qs_net`.
2. Cluster PUT:
   - queue (when the machine name differs),
   - notifier on the target (new notifier and token in Vault), old notifier removed when unused,
   - the PUT also drops HEAppE's cached scheduler.
3. Check from the HEAppE container: `GET http://<alias>:<port>/machine/{m}/about`.
4. Record `previous_*`. The old machine stays suspended (give it another alias for testing, or delete it).

### Switch back
- Reverse of step 2, while the previous instance and machine still exist.
- Tasks created on the target are discarded.

---

## 6. In-place update (replaces today's Update)

Flow: `update_migration/update_flow_in_place.mermaid`.

| Step | What it does |
|---|---|
| Prepare | Build or check the image; collect all clusters of all assigned HEAppE instances; remember pre-existing suspensions. |
| Drain | Suspend every machine; idle check (as in section 5) for all clusters; force with warning; abort lifts only the suspensions set by the update. |
| Backup | Section 2; abort on a failed dump. |
| Replace | `recreate_container`: same env (incl. `ADMIN_TOKEN`), labels, static IPs, aliases, extra hosts. Migrations run on start. |
| Verify | `/health`, version, machines and notifiers via the admin API, suspensions present. |
| Resume | Lift the update's suspensions; check every alias from the HEAppE containers. |
| Rollback | Stop the new container, `pg_restore` the backup, start the renamed old container, lift the suspensions. Tasks created on the new version are discarded. |

Progress is shown in the existing operation dialog.

---

## 7. UI

| Page | Changes |
|---|---|
| QScheduler page | Shared database card (deploy, status, update image, remove). Deploy form: database *Shared (recommended) / Dedicated container (experiments) / Existing URL*, QScheduler network subnet (auto or manual). Instance card: QScheduler network, static IP, aliases, *Migrate to QScheduler network*, backups (*Backup now*, list, delete), *Update* with drain dialog. |
| Clusters page | Add quantum machine: *Alias*. Cluster detail: *Set alias*, *Redirect* (drain → idle status with refresh → switch), *Switch back*. |
| Containers & Services | Extra Hosts tab unchanged; the QScheduler networks appear in the HEAppE override file. |

## 8. Tests

- Schema and role naming.
- SQL statements.
- Shared and dedicated backup and restore commands.
- Override-file networks (keeps other content).
- `recreate_args_from_inspect` with static IP and aliases.
- Alias validation (zone, uniqueness per site).
- Reconnect arguments.
- Redirect preconditions: assignment, machine, shared-machine confirmation.
- Idle check from HEAppE responses.
- In-place update order, and rollback on each failing step.
- A manual end-to-end check against QScheduler `v0.2.1` and PostgreSQL 16, as for the schema test.

## 9. Out of scope

- Remote sites (part b), remote HEAppE (part c).
- Moving existing dedicated-database instances into the shared database.
- PostgreSQL major upgrades.
- A DNS server.
