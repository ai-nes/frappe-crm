#!/bin/bash
set -euo pipefail

BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"

cd "${BENCH_DIR}"

mkdir -p sites/assets

if [ -d /opt/frappe/sites-template/assets ]; then
    cp -r /opt/frappe/sites-template/assets/. sites/assets/
fi

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

chmod -R a+rX sites/assets
