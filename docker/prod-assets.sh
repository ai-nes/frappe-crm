#!/bin/bash
set -euo pipefail

BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"

cd "${BENCH_DIR}"

echo "Syncing production assets into ${BENCH_DIR}/sites/assets"
mkdir -p sites/assets

if id frappe >/dev/null 2>&1; then
    chown -R frappe:frappe sites
fi

if [ -f /opt/frappe/sites-template/assets/assets.json ]; then
    echo "Seeding assets.json from /opt/frappe/sites-template/assets"
    cp /opt/frappe/sites-template/assets/assets.json sites/assets/assets.json
fi

if [ -d /opt/frappe/sites-template/assets/locale ]; then
    echo "Seeding locale assets from /opt/frappe/sites-template/assets"
    rm -rf sites/assets/locale
    mkdir -p sites/assets/locale
    cp -r /opt/frappe/sites-template/assets/locale/. sites/assets/locale/
fi

for app in frappe crm; do
    public_dir="apps/${app}/${app}/public"
    target_dir="sites/assets/${app}"

    if [ -d "${public_dir}" ]; then
        echo "Copying ${public_dir} -> ${target_dir}"
        mkdir -p "${target_dir}"
        cp -r "${public_dir}/." "${target_dir}/"
    else
        echo "Missing public directory: ${public_dir}" >&2
        exit 1
    fi
done

chmod -R a+rX sites/assets

if id frappe >/dev/null 2>&1; then
    chown -R frappe:frappe sites
fi

echo "Verifying synced assets"
test -f sites/assets/assets.json
test -d sites/assets/frappe/dist/css
test -d sites/assets/crm/frontend/assets

ls -lh sites/assets/frappe/dist/css/desk.bundle.*.css
ls -lh sites/assets/frappe/dist/css/report.bundle.*.css
ls -lh sites/assets/frappe/dist/css/website.bundle.*.css
ls -lh sites/assets/crm/frontend/assets/index-*.css
ls -lh sites/assets/crm/frontend/assets/index-*.js

echo "Production assets synced successfully"
