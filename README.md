# heappe-management

## Running with Docker

```
docker compose up -d --build
```

This builds and starts the `management` service (Django app + gunicorn) using
`network_mode: host`, so it binds directly to the Docker host's port 8000.
`MANAGEMENT_PROXYPASS` is left unset, so the app is served at the root instead of under
`/management` — no reverse proxy is required for the container setup.

Where to point the browser depends on the platform:

| Platform | URL | `expose` sidecar |
| --- | --- | --- |
| Native Linux | `http://localhost:8000/` | remove it from `compose.yaml` |
| Docker Desktop (Windows/macOS) | `http://localhost:8080/` | keep it (started by default) |

The container needs the host's Docker socket and CLI (`docker-ce-cli` +
`docker-compose-plugin`) because the app itself shells out to `docker`/`docker compose`
to deploy and manage separate HEAppE instance stacks. It also bind-mounts
`/opt/heappe-deployment` — this must be the **same path on the Docker host** as inside
the container, because the app writes `.env`/config files there that are later used as
bind-mount sources by the daemon when it starts those instance stacks (on Docker
Desktop, "the Docker host" is the Docker Desktop VM, not your Windows/macOS machine).

The app's own SQLite database lives on the named volume `management-db`, not in the
image, so it survives container recreation.

The image excludes `.git` (`.dockerignore`): when the build context is a git worktree,
`.git` is a file pointing at an absolute host path that doesn't exist inside the
container, and git commands run under `/app` — including instance deployment's
`git clone` and the tag/branch pickers, not just the version badge — fail outright if
that path is copied in. Without `.git`, `check_for_updates` takes its tag-fallback path and
returns HTTP 500 (`heappe_ui/views.py:1154-1158`) instead of showing the version badge; this
is fired on every page load for authenticated users (`base.html:676`), but it's fast and
non-fatal — the request just fails silently, the page still loads.

### Docker Desktop (Windows/macOS)

`network_mode: host` containers aren't reachable via the host's `localhost` on Docker
Desktop, so the `expose` service (a small `socat` sidecar) forwards the app to
**`localhost:8080`**. It can't reuse port 8000 itself:
`management` already holds `0.0.0.0:8000` in the Docker Desktop VM's network
namespace (via `network_mode: host`), and Desktop's own port-publishing for a second
container needs that same namespace, so publishing `8000:8000` a second time fails
with "address already in use" — verified by actually trying it.

On native Linux, remove the `expose` service from `compose.yaml` instead: host mode
already exposes port 8000 directly there, and running `expose` too would hit the
exact same port conflict.

### Admin account

`compose.yaml` sets `DJANGO_SUPERUSER_USERNAME`/`_EMAIL`/`_PASSWORD` (default
`admin` / `admin@example.com` / `admin`) — `docker-entrypoint.sh` uses them to create a
superuser via `manage.py createsuperuser --noinput` after `migrate`. The email must be
a syntactically valid address or Django refuses to create the account, hence the
`example.com` default rather than something obviously fake.

This only happens on the **first** run against an empty `management-db` volume; on
later starts the user already exists and creation is skipped. **Change the default
password** before exposing the panel to anyone else, either by setting
`DJANGO_SUPERUSER_PASSWORD` before the first `docker compose up`, or afterwards with:

```
docker compose exec management python manage.py changepassword admin
```

### Instance proxy

The `proxy` service (`nginx:alpine`) exposes every deployed HEAppE instance under its
own path prefix on **`http://localhost:8081/`**, so instances don't each need their own
published port. It's generated dynamically from
`/opt/heappe-deployment/<name>/heappe-core/.env` (`INSTANCE_NAME`, `HOST_APP_PORT`,
`HOST_DATA_STAGING_PORT`) by `proxy/generate-locations.sh`, which (re)writes the nginx
location blocks and reloads nginx only when the instance set actually changed. It
refreshes every **30 seconds** (`REFRESH_INTERVAL`), so a newly deployed (or removed)
instance takes up to that long to appear (or disappear) behind the proxy.

For an instance named `dev`:

| URL prefix | Proxies to |
| --- | --- |
| `/dev/` | its HEAppE API (`HOST_APP_PORT`) |
| `/dev-datastaging/` | its data-staging API (`HOST_DATA_STAGING_PORT`) |

Both are stripped before forwarding (`location /dev/ { proxy_pass http://.../ ; }`),
because HEAppE itself serves at the root of its port and only *advertises* the
`/dev/...` prefix in Swagger (`SwaggerConfiguration.HostPostfix`). A prefix with no
matching instance returns a plain 404 instead of a broken upstream.

Like `expose`, the `proxy` container reaches the instance containers through its own
network's default gateway (`ip route`), not `host.docker.internal`/`extra_hosts`,
for the same reason (see the comment on `expose` in `compose.yaml`). On native Linux,
where instance containers already publish their ports directly on the host, you can
reach them without this sidecar too — keep it only if you want the single aggregated
`:8081` entry point.

### Not supported in the container

The app's in-app self-update (the "update"/redeploy button, `deploy.sh`) restarts
itself via `systemctl`, which assumes a systemd host — it does not work when the app
runs as a container and is not supported in this setup.

### Security

The container runs as root with `/var/run/docker.sock` bind-mounted — that socket is
root-equivalent access to the Docker host. Combined with the repo's `ALLOWED_HOSTS = ['*']`
and checked-in `SECRET_KEY` (`adminpanel/settings.py:41,46`), do not expose this panel to an
untrusted network.
