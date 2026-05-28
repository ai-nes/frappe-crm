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

if [ ! -d "sites/${SITE_NAME}" ]; then
    bench new-site "${SITE_NAME}" \
        --mariadb-root-password "${MYSQL_ROOT_PASSWORD}" \
        --admin-password "${ADMIN_PASSWORD}" \
        --no-mariadb-socket

    bench --site "${SITE_NAME}" install-app crm
fi

bench use "${SITE_NAME}"
bench --site "${SITE_NAME}" migrate
bench --site "${SITE_NAME}" clear-cache
bench build --app crm
