#!/bin/sh
# Regenerates /etc/nginx/generated/locations.conf from the .env of every
# instance under $DEPLOYMENT_ROOT, then (re)starts/reloads nginx whenever
# the set of instances changes. Runs as the proxy container's entrypoint.
set -eu

DEPLOYMENT_ROOT=/opt/heappe-deployment
LOCATIONS_CONF=/etc/nginx/generated/locations.conf
REFRESH_INTERVAL=${REFRESH_INTERVAL:-30}

# HEAppE's own containers are reachable only via the docker bridge's default
# gateway from here (neither host.docker.internal nor extra_hosts:
# host-gateway resolve to the right side on Docker Desktop) - same trick as
# the `expose` sidecar in compose.yaml.
gateway=$(ip route | awk '/default/ {print $3}')

# A stopped/deleted instance leaves its directory (and .env) behind, and its
# recorded port can be reused later by an unrelated instance - a port being
# open is not proof it still belongs to this instance. So before routing to
# it, ask the port itself who it is via /heappe/Health and require the
# InstanceIdentifier it reports to match the directory's name. No match (down,
# still starting, or claimed by someone else) => no location for it this
# round; a 404 beats silently serving the wrong instance's data.
port_belongs_to_instance() {
    port=$1
    name=$2
    health=$(wget -q -T 2 -O - "http://$gateway:$port/heappe/Health" 2>/dev/null) || return 1
    identifier=$(printf '%s' "$health" | sed -n 's/.*"InstanceIdentifier":"\([^"]*\)".*/\1/p')
    [ "$identifier" = "$name" ]
}

# Writes the current instance set to a temp file and swaps it in only if it
# changed, so an unchanged instance list never triggers an nginx reload.
regenerate_locations() {
    tmp=$(mktemp)
    for env_file in "$DEPLOYMENT_ROOT"/*/heappe-core/.env; do
        [ -f "$env_file" ] || continue

        name=$(sed -n 's/^INSTANCE_NAME=//p' "$env_file")
        app_port=$(sed -n 's/^HOST_APP_PORT=//p' "$env_file")
        datastaging_port=$(sed -n 's/^HOST_DATA_STAGING_PORT=//p' "$env_file")
        [ -n "$name" ] && [ -n "$app_port" ] && [ -n "$datastaging_port" ] || continue
        port_belongs_to_instance "$app_port" "$name" || continue

        cat >>"$tmp" <<EOF
location /$name/ {
    proxy_pass http://$gateway:$app_port/;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}
location /$name-datastaging/ {
    proxy_pass http://$gateway:$datastaging_port/;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}
EOF
    done

    if cmp -s "$tmp" "$LOCATIONS_CONF" 2>/dev/null; then
        rm -f "$tmp"
        return 1
    fi
    mkdir -p "$(dirname "$LOCATIONS_CONF")"
    mv "$tmp" "$LOCATIONS_CONF"
    return 0
}

regenerate_locations || true

nginx -g 'daemon off;' &
nginx_pid=$!

while kill -0 "$nginx_pid" 2>/dev/null; do
    sleep "$REFRESH_INTERVAL"
    if regenerate_locations; then
        nginx -s reload
    fi
done
wait "$nginx_pid"
