#!/bin/bash
set -euo pipefail

BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"
DB_HOST="${DB_HOST:-mariadb}"
REDIS_CACHE="${REDIS_CACHE:-redis://redis-cache:6379}"
REDIS_QUEUE="${REDIS_QUEUE:-redis://redis-queue:6379}"
REDIS_SOCKETIO="${REDIS_SOCKETIO:-redis://redis-queue:6379}"
SOCKETIO_PORT="${SOCKETIO_PORT:-9000}"
SYNC_PUBLIC_ASSETS="${SYNC_PUBLIC_ASSETS:-0}"

seed_sites_template() {
    mkdir -p sites
    cp -an /opt/frappe/sites-template/. sites/
}

configure_bench() {
    bench set-mariadb-host "${DB_HOST}"
    bench set-redis-cache-host "${REDIS_CACHE}"
    bench set-redis-queue-host "${REDIS_QUEUE}"
    bench set-redis-socketio-host "${REDIS_SOCKETIO}"
    bench set-config -g socketio_port "${SOCKETIO_PORT}"
}

sync_public_assets() {
    local lock_dir="sites/assets/.sync-public-assets.lock"
    local waited=0

    mkdir -p sites/assets

    until mkdir "${lock_dir}" 2>/dev/null; do
        if [ "${waited}" -ge 60 ]; then
            echo "Timed out waiting for asset sync lock, continuing startup"
            return 0
        fi

        sleep 1
        waited=$((waited + 1))
    done

    cleanup_lock() {
        rm -rf "${lock_dir}"
    }
    trap cleanup_lock EXIT

    for app in frappe crm; do
        local public_dir="apps/${app}/${app}/public"
        local target_dir="sites/assets/${app}"
        local tmp_dir="${target_dir}.tmp.$$"

        if [ -d "${public_dir}" ]; then
            rm -rf "${tmp_dir}"
            mkdir -p "${tmp_dir}"
            cp -a "${public_dir}/." "${tmp_dir}/"
            rm -rf "${target_dir}"
            mv "${tmp_dir}" "${target_dir}"
        fi
    done

    cleanup_lock
    trap - EXIT
}

if [ "$#" -eq 0 ]; then
    echo "Usage: prod-runtime.sh <command> [args...]" >&2
    exit 64
fi

cd "${BENCH_DIR}"
seed_sites_template
configure_bench

if [ "${SYNC_PUBLIC_ASSETS}" = "1" ]; then
    sync_public_assets
fi

exec "$@"
