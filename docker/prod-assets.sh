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
        # `sites/assets` is mounted into the Nginx container, while `apps`
        # exists only in the application image.  Bench may seed an absolute
        # symlink here; it works in the app container but is broken in Nginx.
        # Replace that link with real files so every runtime container can
        # serve the assets from the shared sites volume.
        if [ -L "${target_dir}" ]; then
            echo "Replacing asset symlink ${target_dir} with copied files"
            rm "${target_dir}"
        fi

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
    # This script runs as root when invoked directly as the `assets`
    # service, but also runs as frappe when prod-site.sh calls it at the
    # end of its own (already-frappe) setup - `su` to the user you already
    # are isn't guaranteed to be password-less, so only su when actually
    # root.
    run_as_frappe() {
        if [ "$(id -u)" = "0" ]; then
            su -s /bin/bash frappe -c "$1"
        else
            bash -c "$1"
        fi
    }

    # host_name is normally set by prod-site.sh, but that only runs behind
    # the `setup` profile (deliberately manual, since it also runs
    # migrate/install-app). Repeating the safe, idempotent part - forcing
    # https:// so Frappe never builds an absolute URL (OAuth redirect_uri,
    # emails, webhooks) with the wrong scheme - here means every ordinary
    # deploy self-heals this without anyone having to remember to run the
    # setup profile or exec into a container by hand.
    echo "Ensuring host_name is set for site ${SITE_NAME}"
    run_as_frappe "bench --site '${SITE_NAME}' set-config host_name 'https://${SITE_NAME}'"

    # Without this global flag, Frappe's get_url() (frappe/utils/data.py)
    # assumes an unmanaged bench-dev setup and appends ":${webserver_port}"
    # to every absolute URL it builds - including the OAuth redirect_uri -
    # even when host_name above is correctly set. Repeating it here (on top
    # of prod-site.sh) makes it self-heal the same way host_name does.
    echo "Ensuring restart_systemd_on_update is set (prevents Frappe appending webserver_port to absolute URLs)"
    run_as_frappe "bench set-config -g restart_systemd_on_update 1"

    echo "Clearing cached pages for site ${SITE_NAME}"
    run_as_frappe "bench --site '${SITE_NAME}' clear-website-cache"
    run_as_frappe "bench --site '${SITE_NAME}' clear-cache"
fi
