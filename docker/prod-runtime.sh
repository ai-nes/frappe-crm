#!/bin/bash
set -euo pipefail

BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"
DB_HOST="${DB_HOST:-mariadb}"
REDIS_CACHE="${REDIS_CACHE:-redis://redis-cache:6379}"
REDIS_QUEUE="${REDIS_QUEUE:-redis://redis-queue:6379}"
REDIS_SOCKETIO="${REDIS_SOCKETIO:-redis://redis-queue:6379}"
SOCKETIO_PORT="${SOCKETIO_PORT:-9000}"

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

if [ "$#" -eq 0 ]; then
    echo "Usage: prod-runtime.sh <command> [args...]" >&2
    exit 64
fi

cd "${BENCH_DIR}"
seed_sites_template
configure_bench

exec "$@"
