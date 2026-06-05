#!/bin/bash
set -euo pipefail

BENCH_DIR="/home/frappe/frappe-bench"

sync_public_assets() {
    mkdir -p sites/assets

    for app in frappe crm; do
        public_dir="apps/${app}/${app}/public"
        target_dir="sites/assets/${app}"
        tmp_dir="${target_dir}.tmp.$$"

        if [ -d "${public_dir}" ]; then
            rm -rf "${tmp_dir}"
            mkdir -p "${tmp_dir}"
            cp -a "${public_dir}/." "${tmp_dir}/"
            rm -rf "${target_dir}"
            mv "${tmp_dir}" "${target_dir}"
        fi
    done
}

if [ "$(id -u)" = "0" ]; then
    mkdir -p "${BENCH_DIR}"
    chown frappe:frappe /home/frappe
    chown -R frappe:frappe "${BENCH_DIR}"
    mkdir -p /workspace/node_modules /workspace/frontend/node_modules
    chown -R frappe:frappe /workspace/node_modules /workspace/frontend/node_modules
    exec su -s /bin/bash frappe -c "cd /home/frappe && bash /workspace/docker/init.sh"
fi

if [ -f "${BENCH_DIR}/sites/common_site_config.json" ] \
    && [ -d "${BENCH_DIR}/apps/frappe" ] \
    && "${BENCH_DIR}/env/bin/python" -c "import frappe" >/dev/null 2>&1; then
    echo "Bench already exists, reusing persisted bench data"
else
    echo "Bench directory is missing or incomplete. Recreating bench..."
    mkdir -p "${BENCH_DIR}"
    rm -rf "${BENCH_DIR:?}/"* "${BENCH_DIR:?}/".[!.]* "${BENCH_DIR:?}/"..?* || true
    rm -rf /home/frappe/frappe-bench-tmp || true

    echo "Creating new bench..."
    cd /home/frappe
    bench init --ignore-exist --skip-redis-config-generation --no-backups "${BENCH_DIR}" --version version-15
    test -f "${BENCH_DIR}/sites/common_site_config.json"
fi

cd "${BENCH_DIR}"

# /workspace is a host-mounted Git repo. Inside the container it can appear to be
# owned by a different UID, so bench's Git checks need an explicit trust entry.
if ! git config --global --get-all safe.directory | grep -Fxq /workspace; then
    git config --global --add safe.directory /workspace
fi

# Use containers instead of localhost
bench set-mariadb-host mariadb
bench set-redis-cache-host redis://redis:6379
bench set-redis-queue-host redis://redis:6379
bench set-redis-socketio-host redis://redis:6379

# Remove local redis/watch processes from Procfile if present
sed -i '/redis/d' ./Procfile || true
sed -i '/watch/d' ./Procfile || true

# IMPORTANT: Use local app source mounted at /workspace (repo root), not remote get-app
if [ ! -e "apps/crm" ]; then
    bench get-app /workspace --soft-link
fi

echo "Installing and building CRM frontend assets..."
cd /workspace
yarn install --check-files
yarn build
cd "${BENCH_DIR}"
sync_public_assets

if [ ! -d "sites/crm.localhost" ]; then
    bench new-site crm.localhost \
        --mariadb-root-password 123 \
        --admin-password admin \
        --no-mariadb-socket

    bench --site crm.localhost install-app crm
    bench --site crm.localhost set-config developer_mode 1
    bench --site crm.localhost set-config ignore_csrf 1
    bench --site crm.localhost set-config mute_emails 1
    bench --site crm.localhost set-config server_script_enabled 1
fi

bench --site crm.localhost clear-cache
bench --site crm.localhost migrate
bench use crm.localhost

bench start
