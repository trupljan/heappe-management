# Recovery from error states

HEAppE Management recognises some known error states of a deployed HEAppE instance and offers a fix in the UI.
This file lists each recognised state: how to recognise it, what the admin panel shows, and what its fix does.

Recovery of QScheduler instances and QScheduler clusters is in [QScheduler_Recovery_README.md](QScheduler_Recovery_README.md).

## Contents

- [How recovery works](#how-recovery-works)
- [HEAppE started before SQL Server was ready](#heappe-started-before-sql-server-was-ready)
- [Adding a new recognised state](#adding-a-new-recognised-state)

---

## How recovery works

- The admin panel only proposes a fix. Nothing runs until the admin clicks the button.
- A state is reported only when its cause is clear from the container states and logs, so that the fix will not make
  things worse. In other situations nothing is shown and the usual tools (container logs, restart) remain.
- Each fix changes as little as possible, e.g. restarts one container instead of the whole instance.

---

## HEAppE started before SQL Server was ready

### Symptoms

- HEAppE does not respond; on **Containers & Services** the `heappe` container is *running* but *unhealthy*.
- The `mssql` container is healthy, and `datastagingapi` (same database) usually is too.
- The `heappe` log contains one of:

  ```
  Microsoft.Data.SqlClient.SqlException (0x80131904): A connection was successfully established with the server,
  but then an error occurred during the pre-login handshake. (provider: TCP Provider, error: 35 - An internal exception was caught)
   ---> System.IO.IOException: Unable to read data from the transport connection: Connection reset by peer.
  ```

  ```
  A network-related or instance-specific error occurred while establishing a connection to SQL Server.
  The server was not found or was not accessible.
  ```

  usually followed by `HEAppE.Exceptions.Internal.DbContextException: MigrationError` and `Unhandled exception`.

### Cause

The `heappe` container started while SQL Server was still starting (or stopped). HEAppE checks the database and its
migrations on start, retries for a short time only, and then gives up. The process does not exit, so Docker does not
restart it, and HEAppE stays unhealthy even after SQL Server becomes healthy.

It happens when the containers start without waiting for each other:

| Trigger | Why the order is not kept |
|---|---|
| **Restart All** in HEAppE Management | It runs `docker compose restart`, which restarts all containers at once and ignores the "wait for healthy `mssql`" rule of the compose file. |
| Restart of Docker or of the host | Docker starts the containers by their restart policy, without the compose ordering. |
| Unpausing the containers | All containers continue at once. |
| SQL Server upgrade after a new `mssql/server:2022-latest` image was pulled | The first start runs upgrade scripts for minutes; SQL Server accepts connections but resets them meanwhile. |

The database itself is not affected.

### What the admin panel shows

On **Containers & Services**, a yellow banner *"HEAppE started before SQL Server was ready"*, with:

- the name of the `heappe` container,
- the error line from its log (under *Error from the HEAppE log*),
- the button **Restart HEAppE**, when SQL Server is healthy,
- otherwise the note that SQL Server is not healthy yet, without the button.

### Fix: Restart HEAppE

**Restart HEAppE** restarts only the `heappe` container (`docker restart`). On the new start, SQL Server is ready:
HEAppE finds the database with all migrations applied and becomes healthy in about a minute. The other containers,
the configuration and the data are not changed.

If HEAppE is still unhealthy afterwards, the cause is different: check the `heappe` log in the container card.

### When the banner is shown

All of these must hold:

1. The `heappe` container (compose service `heappe`) is running.
2. Docker reports it **unhealthy**. While it is still *starting* nothing is shown, because HEAppE retries for a while
   and may still come up by itself. With the compose healthcheck this takes about 75 s after the start.
3. Its log **since its last start** contains one of:
   - `pre-login handshake`
   - `A network-related or instance-specific error occurred while establishing a connection to SQL Server`
   - `Server is in script upgrade mode`

The **Restart HEAppE** button is shown only when the `mssql` container is running and healthy.

The check runs:

- when the page is opened,
- during the progress polling after **Restart All**,
- every 10 s for up to 5 minutes while `heappe` is *starting* or *unhealthy* and the page is open.

### Not covered

These states look similar but are not reported, because a restart does not fix them:

| State | What to do |
|---|---|
| `DbContextException: MigrationMismatch` | The database has migrations that this HEAppE version does not know (e.g. after switching to an older branch). Switch to a matching branch, or turn on automatic migration. |
| `mssql` keeps restarting or is unhealthy | Check its log; common causes are too little memory (`OOMKilled`), a full disk, or a damaged database after an unclean shutdown. |
| `Login failed for user 'SA'` | The password in `appsettings.json` and the SQL Server password differ. |

### Manual fix (without the admin panel)

```bash
docker inspect -f '{{.State.Health.Status}}' <instance>_mssql    # wait for "healthy"
docker restart <instance>_heappe
```

### Implementation

- Detection: `detect_heappe_db_startup_issue()` in [heappe_ui/view/deploy.py](heappe_ui/view/deploy.py), used by the
  page load and by the `status_poll` action (field `heappe_db_issue`).
- Banner and polling: `#heappe-db-issue-banner` and `showHeappeDbIssue()` in
  [heappe_ui/templates/deploy.html](heappe_ui/templates/deploy.html). The button uses the existing container action
  `restart`.
- Tests: `HeappeDbStartupIssueTests` in [heappe_ui/tests.py](heappe_ui/tests.py).

---

## Adding a new recognised state

1. Write a detector that returns the details of the state, or `None`. It uses container states, health and logs since
   the last start only, so that it does not report a state that is already fixed.
2. Report it only when the cause is clear and the fix is safe.
3. Show it next to where the admin works (banner on the page), with the evidence (e.g. the log line) and one button.
   Reuse existing actions where possible.
4. Add tests for the state and for similar states that must **not** be reported.
5. Add a section to this file: Symptoms, Cause, What the admin panel shows, Fix, When it is shown, Not covered,
   Manual fix, Implementation.
