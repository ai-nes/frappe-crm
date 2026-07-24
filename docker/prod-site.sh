#!/bin/bash
set -euo pipefail

BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"
SITE_NAME="${SITE_NAME:?SITE_NAME is required}"
MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD is required}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:?ADMIN_PASSWORD is required}"
DB_HOST="${DB_HOST:-mariadb}"
REDIS_CACHE="${REDIS_CACHE:-redis://redis-cache:6379}"
REDIS_QUEUE="${REDIS_QUEUE:-redis://redis-queue:6379}"
REDIS_SOCKETIO="${REDIS_SOCKETIO:-redis://redis-queue:6379}"
SOCKETIO_PORT="${SOCKETIO_PORT:-9000}"

cd "${BENCH_DIR}"

mkdir -p sites
cp -an /opt/frappe/sites-template/. sites/

bench set-mariadb-host "${DB_HOST}"
bench set-redis-cache-host "${REDIS_CACHE}"
bench set-redis-queue-host "${REDIS_QUEUE}"
bench set-redis-socketio-host "${REDIS_SOCKETIO}"
bench set-config -g socketio_port "${SOCKETIO_PORT}"
bench set-config -g developer_mode 0
bench set-config -g maintenance_mode 0
# Without restart_supervisor_on_update/restart_systemd_on_update, Frappe's
# get_url() (frappe/utils/data.py) treats this as a bare bench-dev setup and
# appends ":${webserver_port}" to every absolute URL it builds - including
# the OAuth redirect_uri - even when host_name is explicitly set. This
# container is never managed by supervisor/systemd, but setting this flag is
# the documented way to tell Frappe "production mode, don't touch host_name".
bench set-config -g restart_systemd_on_update 1

if [ ! -d "sites/${SITE_NAME}" ]; then
    bench new-site "${SITE_NAME}" \
        --mariadb-root-password "${MYSQL_ROOT_PASSWORD}" \
        --admin-password "${ADMIN_PASSWORD}" \
        --no-mariadb-socket

    bench --site "${SITE_NAME}" install-app crm
fi

bench use "${SITE_NAME}"
# install-app is idempotent (no-op if already installed), so this stays safe
# to run on every deploy rather than only when the site is first created.
bench --site "${SITE_NAME}" install-app dfp_external_storage
bench --site "${SITE_NAME}" migrate
# Force https:// regardless of what X-Forwarded-Proto the reverse proxy in
# front of nginx sends - nginx itself only listens on plain HTTP, so
# without this any absolute URL Frappe builds (OAuth redirect_uri, emails,
# webhooks) can end up http:// even when the site is only ever reachable
# over https.
bench --site "${SITE_NAME}" set-config host_name "https://${SITE_NAME}"
bench --site "${SITE_NAME}" clear-website-cache
bench --site "${SITE_NAME}" clear-cache
bash /opt/frappe/scripts/prod-assets.sh
