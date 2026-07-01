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

# Every regular deploy re-syncs content-hashed asset filenames above, but
# Frappe also caches rendered guest pages (like /login) in Redis, which is
# a long-lived service that outlives this one-shot container. Without
# clearing that cache here too, a stale cached page keeps pointing at the
# previous deploy's asset hashes until something else happens to clear it -
# confirmed in practice on a sibling project (frappe/lms) as 404s on
# *.bundle.*.css/js that an asset resync alone did not fix.
#
# Skipped on the very first deploy: SITE_NAME is only set on this service
# once `docker/prod-site.sh` (the `setup` profile) has actually created
# sites/${SITE_NAME}, and there's nothing cached yet to clear anyway.
if [ -n "${SITE_NAME:-}" ] && [ -d "sites/${SITE_NAME}" ]; then
    echo "Clearing cached pages for site ${SITE_NAME}"
    # This script runs as root when invoked directly as the `assets`
    # service, but also runs as frappe when prod-site.sh calls it at the
    # end of its own (already-frappe) setup - `su` to the user you already
    # are isn't guaranteed to be password-less, so only su when actually
    # root.
    if [ "$(id -u)" = "0" ]; then
        su -s /bin/bash frappe -c "bench --site '${SITE_NAME}' clear-website-cache"
        su -s /bin/bash frappe -c "bench --site '${SITE_NAME}' clear-cache"
    else
        bench --site "${SITE_NAME}" clear-website-cache
        bench --site "${SITE_NAME}" clear-cache
    fi
fi
