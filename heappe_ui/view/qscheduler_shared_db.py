"""
Shared PostgreSQL for QScheduler instances, and database backups.

Shared database (one per Docker host; this module manages the one on the host of HEAppE Management)
  * Container "qscheduler-shared-pgsql" (postgres:16), volume "qscheduler-shared-pgdata", database "qscheduler",
    home network "qscheduler-shared-db_net" (internal), no published port. The host backup directory is mounted at
    /backups. Admin SQL runs with `docker exec ... psql` and is passed on stdin (passwords never on a command line).
  * Each QScheduler instance using it gets a role and a schema of the same name ("qs_<instance>"), the role's
    search_path set to it (QScheduler's migrations then create their tables there), CONNECT on the database only.
    The container joins the instance's internal "<name>_db_net", so every instance reaches the database only through
    its own network, and roles cannot read each other's schemas.
  * Update image: same PostgreSQL major version only (recreated on the same volume). Remove: only without instances.

Backups
  * <QSCHEDULER_BACKUP_DIR>/<instance>/<UTC timestamp>[_<qscheduler version>].dump (pg_dump custom format), checked
    with pg_restore --list. Shared: pg_dump -n <schema> in the shared container (writes to /backups). Dedicated: pg_dump
    in the instance's PostgreSQL container, copied out with docker cp. External databases are not backed up here.
"""
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timezone

from django.conf import settings

from heappe_ui.models import QSchedulerDatabase, QSchedulerInstance as Q

from . import qscheduler_core as core
from .qscheduler_core import DockerCli, LABEL_INSTANCE

SHARED_NAME = "qscheduler-shared-pgsql"
SHARED_VOLUME = "qscheduler-shared-pgdata"
SHARED_NETWORK = "qscheduler-shared-db_net"
SHARED_DATABASE = "qscheduler"
LABEL_SHARED_DB = "qscheduler.shared-database"
IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
BACKUP_FILE_RE = re.compile(r"^\d{8}T\d{6}Z(_[A-Za-z0-9.+-]{1,40})?\.dump$")


def shared_image():
    return getattr(settings, "QSCHEDULER_SHARED_DB_IMAGE", None) or os.getenv("QSCHEDULER_SHARED_DB_IMAGE",
                                                                              core.DEFAULT_POSTGRES_IMAGE)


def backup_root():
    return getattr(settings, "QSCHEDULER_BACKUP_DIR", None) or os.getenv(
        "QSCHEDULER_BACKUP_DIR", "/opt/heappe-deployment/qscheduler-backups")


def shared_database():
    return QSchedulerDatabase.objects.first()


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

def ident(name):
    """A validated, double-quoted SQL identifier (role / schema)."""
    if not IDENT_RE.match(name or ""):
        raise ValueError(f"Invalid database identifier: {name!r}")
    return f'"{name}"'


def schema_name_for(instance_name):
    """Role and schema name of an instance: qs_<name>, lowercase, [a-z0-9_] only, max 63 chars."""
    base = re.sub(r"[^a-z0-9_]", "_", instance_name.lower())
    return ("qs_" + base)[:63]


def psql(docker, sql, log=None, db=SHARED_DATABASE, container=SHARED_NAME, user="postgres", check=True):
    """Runs SQL in the shared container (on stdin: never logged, never on a command line); returns stdout."""
    res = docker.run(["exec", "-i", container, "psql", "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-U", user,
                      "-d", db], log, check=False, quiet=True, input=sql)
    if check and res.returncode != 0:
        raise RuntimeError(f"SQL in '{container}' failed: {res.output.strip()[-1500:]}")
    return res.stdout


def create_schema_sql(role, password, database=SHARED_DATABASE):
    r = ident(role)
    if not re.match(r"^[A-Za-z0-9]{16,128}$", password):
        raise ValueError("Unsupported password characters.")
    return (f"CREATE ROLE {r} LOGIN PASSWORD '{password}';\n"
            f"CREATE SCHEMA {r} AUTHORIZATION {r};\n"
            f"ALTER ROLE {r} SET search_path = {r};\n"
            f"GRANT CONNECT ON DATABASE {ident(database)} TO {r};\n")


def drop_schema_sql(role):
    r = ident(role)
    return (f"DROP SCHEMA IF EXISTS {r} CASCADE;\n"
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN "
            f"EXECUTE 'DROP OWNED BY {r}'; EXECUTE 'DROP ROLE {r}'; END IF; END $$;\n")


HARDENING_SQL = (f"REVOKE ALL ON SCHEMA public FROM PUBLIC;\n"
                 f"REVOKE ALL ON DATABASE {SHARED_DATABASE} FROM PUBLIC;\n")


# ---------------------------------------------------------------------------
# Shared database server
# ---------------------------------------------------------------------------

def shared_run_args(db, image=None, name=None):
    return ["run", "-d", "--name", name or db.name, "--restart", "unless-stopped",
            "--label", f"{LABEL_SHARED_DB}={db.name}", "--network", db.home_network, "--shm-size", "256m",
            "-v", f"{db.volume}:/var/lib/postgresql/data", "-v", f"{db.backup_dir}:/backups",
            "-e", f"POSTGRES_PASSWORD={db.admin_password}", "-e", f"POSTGRES_DB={db.database}",
            image or db.image]


def wait_ready(docker, container, log, timeout=90):
    log(f"Waiting for PostgreSQL in '{container}' (timeout {timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        # pg_isready on TCP: the server is past the init phase (the init server listens on the socket only)
        if docker.run(["exec", container, "pg_isready", "-U", "postgres", "-h", "127.0.0.1"], check=False,
                      quiet=True).returncode == 0:
            log("PostgreSQL is ready.")
            return
        time.sleep(1)
    raise RuntimeError(f"PostgreSQL in '{container}' did not become ready within {timeout}s.")


def server_major(docker, container=SHARED_NAME):
    out = psql(docker, "SHOW server_version_num;", container=container).strip()
    return int(out) // 10000 if out.isdigit() else None


def image_major(docker, image):
    res = docker.run(["run", "--rm", "--entrypoint", "postgres", image, "--version"], check=False, quiet=True,
                     timeout=600)
    m = re.search(r"PostgreSQL\)?\s+(\d+)", res.stdout or "")
    return int(m.group(1)) if m else None


def deploy_shared_worker(log, result, opts):
    docker = DockerCli()
    if shared_database():
        raise RuntimeError("A shared database is already deployed.")
    if docker.exists("container", SHARED_NAME):
        raise RuntimeError(f"Container '{SHARED_NAME}' already exists on this Docker host; remove it first.")
    log(f"=== QSCHEDULER: DEPLOY SHARED DATABASE '{SHARED_NAME}' ({opts['image']}) ===")
    backup_dir = backup_root()
    os.makedirs(backup_dir, exist_ok=True)
    db = QSchedulerDatabase(name=SHARED_NAME, image=opts['image'], volume=SHARED_VOLUME, database=SHARED_DATABASE,
                            home_network=SHARED_NETWORK, backup_dir=backup_dir)
    db.admin_password = secrets.token_hex(24)
    created = []
    try:
        if not docker.json(["network", "inspect", SHARED_NETWORK]):
            core.create_internal_network(docker, SHARED_NETWORK, {LABEL_SHARED_DB: SHARED_NAME}, log, prefix=29)
            created.append(("network", SHARED_NETWORK))
        if not docker.json(["volume", "inspect", SHARED_VOLUME]):
            docker.run(["volume", "create", "--label", f"{LABEL_SHARED_DB}={SHARED_NAME}", SHARED_VOLUME], log)
            created.append(("volume", SHARED_VOLUME))
        else:
            raise RuntimeError(f"Volume '{SHARED_VOLUME}' already exists (a previous shared database?). Remove it or "
                               f"rename it before deploying a new shared database.")
        docker.run(shared_run_args(db), log)
        created.append(("container", SHARED_NAME))
        wait_ready(docker, SHARED_NAME, log)
        psql(docker, HARDENING_SQL, log)
        log("Public schema and database closed to other roles (each instance gets its own role and schema).")
    except Exception:
        for kind, name in reversed(created):
            docker.run(["rm", "-f", name] if kind == "container" else [kind, "rm", name], log, check=False)
        raise
    db.save()
    result.update({'name': db.name, 'backup_dir': backup_dir})
    log(f"SUCCESS: shared database '{db.name}' is running; backups go to {backup_dir}.")


def update_shared_worker(log, result, opts, uid):
    """New image of the same PostgreSQL major version: recreate on the same volume, rejoin all networks."""
    docker = DockerCli()
    db = shared_database()
    if not db:
        raise RuntimeError("No shared database is deployed.")
    image = opts['image']
    log(f"=== QSCHEDULER: UPDATE SHARED DATABASE '{db.name}' to {image} ===")
    info = docker.inspect(db.name)
    if not info:
        raise RuntimeError(f"Container '{db.name}' not found.")
    docker.run(["pull", image], log, check=False, timeout=900)
    old_major, new_major = server_major(docker, db.name), image_major(docker, image)
    if not old_major or not new_major:
        raise RuntimeError(f"Could not determine the PostgreSQL versions (running {old_major}, image {new_major}).")
    if old_major != new_major:
        raise RuntimeError(f"Image '{image}' is PostgreSQL {new_major}, the server is {old_major}: major upgrades need "
                           f"a dump and restore and are not supported here.")
    networks = [n for n in ((info.get("NetworkSettings") or {}).get("Networks") or {}) if n != db.home_network]
    log(f"QScheduler instances lose the database for a few seconds (they reconnect); networks: "
        f"{', '.join(networks) or 'none'}.")
    backup = f"{db.name}-old-{uid}"
    docker.run(["stop", db.name], log)
    docker.run(["rename", db.name, backup], log)
    try:
        docker.run(shared_run_args(db, image), log)
        for net in networks:
            docker.run(["network", "connect", net, db.name], log)
        wait_ready(docker, db.name, log)
    except Exception as ex:
        log(f"Update failed ({str(ex).splitlines()[0]}); rolling back...")
        docker.run(["rm", "-f", db.name], log, check=False)
        docker.run(["rename", backup, db.name], log, check=False)
        docker.run(["start", db.name], log, check=False)
        raise RuntimeError(f"Update failed and was rolled back: {ex}")
    docker.run(["rm", backup], log)
    db.image = image
    db.save(update_fields=["image", "updated_at"])
    result.update({'name': db.name, 'image': image})
    log(f"SUCCESS: shared database runs {image}.")


def remove_shared_worker(log, result, remove_data):
    docker = DockerCli()
    db = shared_database()
    if not db:
        raise RuntimeError("No shared database is deployed.")
    users = list(Q.objects.filter(shared_database=db).values_list("name", flat=True))
    if users:
        raise RuntimeError(f"Instances still use the shared database: {', '.join(users)}. Undeploy them first.")
    log(f"=== QSCHEDULER: REMOVE SHARED DATABASE '{db.name}' ===")
    docker.run(["rm", "-f", db.name], log, check=False)
    if docker.json(["network", "inspect", db.home_network]):
        docker.run(["network", "rm", db.home_network], log, check=False)
    if remove_data:
        docker.run(["volume", "rm", db.volume], log, check=False)
    else:
        log(f"Kept volume '{db.volume}' (remove with: docker volume rm {db.volume}).")
    db.delete()
    result['name'] = SHARED_NAME
    log("SUCCESS: shared database removed.")


def shared_status():
    """Card data: deployed, running, version, schemas (size, instance, connections)."""
    db = shared_database()
    if not db:
        return {'deployed': False, 'image': shared_image()}
    docker = DockerCli()
    info = docker.inspect(db.name) or {}
    out = {'deployed': True, 'name': db.name, 'image': db.image, 'volume': db.volume, 'backup_dir': db.backup_dir,
           'running': (info.get("State") or {}).get("Status") == "running", 'exists': bool(info),
           'version': None, 'schemas': [], 'error': None}
    if not out['running']:
        return out
    try:
        out['version'] = psql(docker, "SHOW server_version;").strip()
        rows = psql(docker, (
            "SELECT n.nspname, COALESCE(sum(pg_total_relation_size(c.oid)), 0), "
            "(SELECT count(*) FROM pg_stat_activity a WHERE a.usename = n.nspname) "
            "FROM pg_namespace n LEFT JOIN pg_class c ON c.relnamespace = n.oid "
            "WHERE n.nspname LIKE 'qs\\_%' GROUP BY n.nspname ORDER BY n.nspname;"))
        owners = {i.db_schema: i.name for i in Q.objects.filter(shared_database=db)}
        for line in rows.splitlines():
            parts = line.split("|")
            if len(parts) == 3:
                out['schemas'].append({'schema': parts[0], 'size': int(parts[1] or 0), 'connections': int(parts[2] or 0),
                                       'instance': owners.get(parts[0])})
    except Exception as e:
        out['error'] = str(e).splitlines()[0][:300]
    return out


# ---------------------------------------------------------------------------
# Instances in the shared database
# ---------------------------------------------------------------------------

def require_running(docker):
    db = shared_database()
    if not db:
        raise RuntimeError("No shared database is deployed: deploy it first (QScheduler page) or choose another "
                           "database option.")
    info = docker.inspect(db.name) or {}
    if (info.get("State") or {}).get("Status") != "running":
        raise RuntimeError(f"Shared database '{db.name}' is not running.")
    return db


def schema_exists(docker, role):
    return psql(docker, f"SELECT 1 FROM pg_namespace WHERE nspname = '{ident(role)[1:-1]}';").strip() == "1"


def role_exists(docker, role):
    return psql(docker, f"SELECT 1 FROM pg_roles WHERE rolname = '{ident(role)[1:-1]}';").strip() == "1"


def create_instance_schema(docker, db, instance_name, log):
    """Role + schema for a new instance; returns (role, password)."""
    role = schema_name_for(instance_name)
    if role_exists(docker, role) or schema_exists(docker, role):
        raise RuntimeError(f"Role or schema '{role}' already exists in the shared database (a previous instance with "
                           f"this name?). Drop it on the shared database card or choose another name.")
    password = secrets.token_hex(24)
    psql(docker, create_schema_sql(role, password, db.database), log)
    log(f"Role and schema '{role}' created in the shared database (search_path = {role}).")
    return role, password


def drop_instance_schema(docker, role, log):
    psql(docker, drop_schema_sql(role), log)
    log(f"Schema and role '{role}' dropped from the shared database (machines, notifiers, projects, task history).")


def connect_network(docker, db, network, log):
    if network not in ((docker.inspect(db.name) or {}).get("NetworkSettings") or {}).get("Networks", {}):
        docker.run(["network", "connect", network, db.name], log)


def disconnect_network(docker, db, network, log):
    if network in ((docker.inspect(db.name) or {}).get("NetworkSettings") or {}).get("Networks", {}):
        docker.run(["network", "disconnect", network, db.name], log, check=False)


def drop_orphan_schema_worker(log, result, role):
    """Drop a qs_ schema that no registered instance uses (e.g. left by a restore under another name)."""
    docker = DockerCli()
    require_running(docker)
    if Q.objects.filter(db_schema=role, db_kind=Q.DB_SHARED).exists():
        raise RuntimeError(f"Schema '{role}' belongs to a registered instance; undeploy it instead.")
    log(f"=== QSCHEDULER: DROP UNUSED SCHEMA '{role}' ===")
    drop_instance_schema(docker, role, log)
    result['schema'] = role
    log("SUCCESS: schema dropped.")


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------

def backup_dir_of(inst):
    return os.path.join(backup_root(), inst.container_name or inst.name)


def can_backup(inst):
    return inst.kind == Q.KIND_MANAGED and inst.db_kind in (Q.DB_SHARED, Q.DB_DEDICATED)


def backup_file_name(version=None, now=None):
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    ver = re.sub(r"[^A-Za-z0-9.+-]", "", (version or "").split()[-1] if version else "")[:40]
    return f"{stamp}{'_' + ver if ver else ''}.dump"


def list_backups(inst):
    d = backup_dir_of(inst)
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d), reverse=True):
        if BACKUP_FILE_RE.match(f):
            st = os.stat(os.path.join(d, f))
            out.append({'file': f, 'size': st.st_size,
                        'created': datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")})
    return out


def delete_backup(inst, file):
    if not BACKUP_FILE_RE.match(file or ""):
        raise ValueError("Invalid backup file name.")
    path = os.path.join(backup_dir_of(inst), file)
    if not os.path.isfile(path):
        raise FileNotFoundError(file)
    os.remove(path)


def _dump_tables(listing):
    return sum(1 for line in (listing or "").splitlines() if " TABLE " in line and " TABLE DATA " not in line)


def backup_instance(inst, log, version=None):
    """pg_dump of the instance's database into its backup directory; returns the host path."""
    if not can_backup(inst):
        raise RuntimeError("Backups are available for instances deployed by HEAppE Management (shared or dedicated "
                           "database).")
    docker = DockerCli()
    d = backup_dir_of(inst)
    os.makedirs(d, exist_ok=True)                 # created by HEAppE Management: its files can be deleted from the UI
    file = backup_file_name(version)
    host_path = os.path.join(d, file)
    if inst.db_kind == Q.DB_SHARED:
        db = require_running(docker)
        rel = os.path.relpath(host_path, db.backup_dir)
        if rel.startswith(".."):
            raise RuntimeError(f"Backup directory {d} is not inside the shared database mount {db.backup_dir}.")
        path = f"/backups/{rel}"
        docker.run(["exec", db.name, "pg_dump", "-U", "postgres", "-d", db.database, "-Fc", "-n", inst.db_schema,
                    "-f", path], log, timeout=3600)
        listing = docker.run(["exec", db.name, "pg_restore", "--list", path], log, check=False, quiet=True)
    else:
        pg = f"{inst.container_name}-pgsql"
        tmp = f"/tmp/qs-backup-{uuid.uuid4().hex[:8]}.dump"
        try:
            docker.run(["exec", pg, "pg_dump", "-U", "qscheduler", "-d", "qscheduler", "-Fc", "-f", tmp], log,
                       timeout=3600)
            listing = docker.run(["exec", pg, "pg_restore", "--list", tmp], log, check=False, quiet=True)
            if listing.returncode == 0:
                docker.run(["cp", f"{pg}:{tmp}", host_path], log, timeout=3600)
        finally:
            docker.run(["exec", pg, "rm", "-f", tmp], check=False, quiet=True)
    tables = _dump_tables(listing.stdout) if listing.returncode == 0 else 0
    if not tables or not os.path.isfile(host_path):
        if os.path.isfile(host_path):
            os.remove(host_path)
        raise RuntimeError(f"Backup check failed (pg_restore --list: {listing.output.strip()[-300:] or 'no tables'}).")
    log(f"Backup {host_path}: {os.path.getsize(host_path)} bytes, {tables} tables.")
    return host_path


def restore_instance(inst, file, log):
    """Restores a backup into the instance's database (the QScheduler service must be stopped)."""
    if not BACKUP_FILE_RE.match(file or ""):
        raise ValueError("Invalid backup file name.")
    docker = DockerCli()
    host_path = os.path.join(backup_dir_of(inst), file)
    if not os.path.isfile(host_path):
        raise RuntimeError(f"Backup {host_path} not found.")
    if inst.db_kind == Q.DB_SHARED:
        db = require_running(docker)
        path = "/backups/" + os.path.relpath(host_path, db.backup_dir)
        docker.run(["exec", db.name, "pg_restore", "-U", "postgres", "-d", db.database, "--clean", "--if-exists",
                    "-n", inst.db_schema, path], log, timeout=3600)
    elif inst.db_kind == Q.DB_DEDICATED:
        pg = f"{inst.container_name}-pgsql"
        tmp = f"/tmp/qs-restore-{uuid.uuid4().hex[:8]}.dump"
        try:
            docker.run(["cp", host_path, f"{pg}:{tmp}"], log, timeout=3600)
            docker.run(["exec", pg, "pg_restore", "-U", "qscheduler", "-d", "qscheduler", "--clean", "--if-exists",
                        tmp], log, timeout=3600)
        finally:
            docker.run(["exec", pg, "rm", "-f", tmp], check=False, quiet=True)
    else:
        raise RuntimeError("Restore is available for shared and dedicated databases only.")
    log(f"Database of '{inst.name}' restored from {file}.")


def backup_worker(log, result, inst_id):
    inst = Q.objects.get(pk=inst_id)
    log(f"=== QSCHEDULER: BACKUP DATABASE OF '{inst.name}' ===")
    version = None
    target = None
    try:
        target = core.target_for(inst)
        version = target.version()
    except Exception:
        pass
    finally:
        if target:
            target.close()
    path = backup_instance(inst, log, version)
    result.update({'name': inst.name, 'file': os.path.basename(path)})
    log("SUCCESS: backup created.")


# ---------------------------------------------------------------------------
# Migration of a dedicated database into the shared database
# ---------------------------------------------------------------------------

def table_counts(docker, container, user, database, schema):
    """{table: row count} of the base tables in `schema`."""
    tables = [t for t in psql(docker, f"SELECT table_name FROM information_schema.tables WHERE table_schema = "
                                      f"'{ident(schema)[1:-1]}' AND table_type = 'BASE TABLE' ORDER BY 1;",
                              db=database, container=container, user=user).split() if t]
    if not tables:
        return {}
    union = " UNION ALL ".join(f"SELECT '{t}', count(*) FROM {ident(schema)}.\"{t}\"" for t in tables
                               if re.match(r"^[A-Za-z0-9_]+$", t))
    out = {}
    for line in psql(docker, union + ";", db=database, container=container, user=user).splitlines():
        name, _, count = line.partition("|")
        if name:
            out[name] = int(count or 0)
    return out


def migrate_sql_steps(role, password, tmp_db, database=SHARED_DATABASE):
    """SQL of the migration, in order: (database, sql) pairs run as the shared database's superuser."""
    r = ident(role)
    if not re.match(r"^[A-Za-z0-9]{16,128}$", password):
        raise ValueError("Unsupported password characters.")
    return {
        'role': (database, f"CREATE ROLE {r} LOGIN PASSWORD '{password}';\n"),
        'tmp_db': (database, f"CREATE DATABASE {ident(tmp_db)} OWNER {r};\n"),
        # restored as the role into the temporary database's public schema, then renamed to the role's schema
        'rename': (tmp_db, f"ALTER SCHEMA public RENAME TO {r};\nALTER SCHEMA {r} OWNER TO {r};\n"),
        'grants': (database, f"ALTER ROLE {r} SET search_path = {r};\nGRANT CONNECT ON DATABASE {ident(database)} TO {r};\n"),
        'drop_tmp': (database, f"DROP DATABASE IF EXISTS {ident(tmp_db)};\n"),
    }


def migrate_to_shared_worker(log, result, inst_id, opts, uid):
    """
    Dedicated PostgreSQL container -> role and schema in the shared database. The QScheduler service is stopped during
    the copy (like a restart: running backend work is re-attached afterwards); the old container and volume are kept
    stopped (or removed when opts['remove_old']), and a backup of the old database is written first.
    """
    from .qscheduler_deploy import recreate_container
    inst = Q.objects.get(pk=inst_id)
    if inst.kind != Q.KIND_MANAGED or inst.db_kind != Q.DB_DEDICATED:
        raise RuntimeError("Only instances deployed by HEAppE Management with a dedicated PostgreSQL container can be "
                           "migrated to the shared database.")
    docker = DockerCli()
    db = require_running(docker)
    name = inst.container_name
    pg, net = f"{name}-pgsql", f"{name}_db_net"
    role = schema_name_for(name)
    tmp_db = f"qsmig_{uid}"
    log(f"=== QSCHEDULER: MIGRATE '{inst.name}' TO THE SHARED DATABASE (schema {role}) ===")
    info = docker.inspect(name)
    if not info:
        raise RuntimeError(f"Container '{name}' not found.")
    if not docker.exists("container", pg):
        raise RuntimeError(f"PostgreSQL container '{pg}' not found.")
    if role_exists(docker, role) or schema_exists(docker, role):
        raise RuntimeError(f"Role or schema '{role}' already exists in the shared database; drop it on the shared "
                           f"database card first.")
    target = core.target_for(inst)
    version = None
    try:
        version = target.version()
    except Exception:
        pass
    password = secrets.token_hex(24)
    steps = migrate_sql_steps(role, password, tmp_db, db.database)
    created_role = False
    switched = False
    try:
        log("Stopping QScheduler for a consistent copy (requests fail until it is back; running backend work is "
            "re-attached).")
        docker.run(["stop", name], log)
        docker.run(["start", pg], log, check=False)
        wait_ready_dedicated = lambda: docker.run(["exec", pg, "pg_isready", "-U", "qscheduler", "-h", "127.0.0.1"],
                                                  check=False, quiet=True).returncode == 0
        for _ in range(30):
            if wait_ready_dedicated():
                break
            time.sleep(1)
        before = table_counts(docker, pg, "qscheduler", "qscheduler", "public")
        log(f"Old database: {len(before)} tables, {sum(before.values())} rows.")

        dump = backup_instance(inst, log, version)          # also the safety backup of the old database
        rel = os.path.relpath(dump, db.backup_dir)
        if rel.startswith(".."):
            raise RuntimeError(f"Backup {dump} is not inside the shared database mount {db.backup_dir}.")

        psql(docker, steps['role'][1], log)
        created_role = True
        psql(docker, steps['tmp_db'][1], log)
        docker.run(["exec", db.name, "pg_restore", "-U", "postgres", "-d", tmp_db, "--no-owner", "--no-privileges",
                    f"--role={role}", f"/backups/{rel}"], log, timeout=3600)
        psql(docker, steps['rename'][1], log, db=tmp_db)
        tmp_dump = f"/backups/{os.path.dirname(rel)}/migrate-{uid}.dump"
        docker.run(["exec", db.name, "pg_dump", "-U", "postgres", "-d", tmp_db, "-Fc", "-n", role, "-f", tmp_dump],
                   log, timeout=3600)
        docker.run(["exec", db.name, "pg_restore", "-U", "postgres", "-d", db.database, tmp_dump], log, timeout=3600)
        docker.run(["exec", db.name, "rm", "-f", tmp_dump], log, check=False, quiet=True)
        psql(docker, steps['grants'][1], log)
        psql(docker, steps['drop_tmp'][1], log)

        after = table_counts(docker, db.name, "postgres", db.database, role)
        if after != before:
            diff = {t: (before.get(t), after.get(t)) for t in set(before) | set(after) if before.get(t) != after.get(t)}
            raise RuntimeError(f"Copied data differs from the old database: {diff}")
        log(f"Data copied and checked: {len(after)} tables, {sum(after.values())} rows in schema '{role}'.")

        connect_network(docker, db, net, log)
        url = f"postgres://{role}:{password}@{db.name}:5432/{db.database}"
        image = (info.get("Config") or {}).get("Image") or inst.image
        recreate_container(docker, target, info, image, None, log, uid, "Switching to the shared database",
                           None, {"DATABASE_URL": url})
        switched = True
    except Exception:
        log("Migration failed; cleaning up the shared database and starting QScheduler on the old database...")
        try:
            psql(docker, steps['drop_tmp'][1], check=False)
            if created_role and not switched:
                psql(docker, drop_schema_sql(role), check=False)
            if not switched:
                disconnect_network(docker, db, net, log)
                docker.run(["start", pg], log, check=False)
                docker.run(["start", name], log, check=False)
        finally:
            target.close()
        raise
    target.close()

    inst.database_url = url
    inst.db_kind, inst.db_schema, inst.shared_database = Q.DB_SHARED, role, db
    inst.save(update_fields=["database_url_encrypted", "db_kind", "db_schema", "shared_database", "updated_at"])
    if opts.get('remove_old'):
        docker.run(["rm", "-f", pg], log, check=False)
        docker.run(["volume", "rm", f"{name}-pgdata"], log, check=False)
        log(f"Old PostgreSQL container '{pg}' and volume '{name}-pgdata' removed.")
    else:
        docker.run(["stop", pg], log, check=False)
        log(f"Old PostgreSQL container '{pg}' stopped and kept with its volume (remove it with: docker rm {pg}; "
            f"docker volume rm {name}-pgdata).")
    result.update({'name': inst.name, 'schema': role, 'backup': os.path.basename(dump)})
    log(f"SUCCESS: '{inst.name}' uses schema '{role}' in the shared database (backup of the old database: "
        f"{os.path.basename(dump)}).")
