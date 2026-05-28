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

sync_public_assets() {
    mkdir -p sites/assets

    for app in frappe crm; do
        public_dir="apps/${app}/${app}/public"
        target_dir="sites/assets/${app}"

        if [ -d "${public_dir}" ]; then
            rm -rf "${target_dir}"
            mkdir -p "${target_dir}"
            cp -a "${public_dir}/." "${target_dir}/"
        fi
    done
}

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
sync_public_assets
