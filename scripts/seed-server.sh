#!/usr/bin/env bash
# Seed the curated CRM demo dataset on a deployed server (demo / staging).
#
# Deploys only run `bench migrate`; this is the manual, deliberate way to
# populate demo data (schools + coordinates, 100 students, campaigns, ...).
# It refuses to run without you re-typing the site name, and it never seeds
# the shared-password test logins on a non-local site.
#
#   Usage (on the server, from the compose directory, e.g. /opt/frappe-crm):
#     bash scripts/seed-server.sh
#     COMPOSE_DIR=/opt/frappe-crm bash scripts/seed-server.sh
#     bash scripts/seed-server.sh --skip-verify

set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-$(pwd)}"
COMPOSE_FILE="${COMPOSE_FILE:-docker/docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-docker/.env}"
SERVICE="${SEED_SERVICE:-backend}"
SKIP_VERIFY=0
[ "${1:-}" = "--skip-verify" ] && SKIP_VERIFY=1

cd "$COMPOSE_DIR"
[ -f "$COMPOSE_FILE" ] || { echo "compose file not found: $COMPOSE_DIR/$COMPOSE_FILE" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "env file not found: $COMPOSE_DIR/$ENV_FILE" >&2; exit 1; }

SITE_NAME="$(grep -E '^SITE_NAME=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
[ -n "$SITE_NAME" ] || { echo "SITE_NAME not set in $ENV_FILE" >&2; exit 1; }

dc() { sudo docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }
bench_exec() { dc exec -T "$SERVICE" bench --site "$SITE_NAME" "$@"; }

cat <<EOF

  This SEEDS DEMO DATA into:   $SITE_NAME
  Container service:          $SERVICE  ($COMPOSE_DIR/$COMPOSE_FILE)

  Demo data (fake students, campaigns, edge-case records) does NOT belong on a
  real production site. Only continue on a demo / staging deployment.

EOF
read -r -p "Type the site name to confirm: " CONFIRM
[ "$CONFIRM" = "$SITE_NAME" ] || { echo "Mismatch — aborted." >&2; exit 1; }

echo "==> allow_demo_seed = 1"
bench_exec set-config allow_demo_seed 1

cleanup() {
    echo "==> allow_demo_seed = 0"
    bench_exec set-config allow_demo_seed 0 || true
}
trap cleanup EXIT

echo "==> ensure_demo_config"
bench_exec execute crm.demo.seed_showcase.ensure_demo_config
echo "==> ensure_local_integrity_keys"
bench_exec execute crm.demo.seed_showcase.ensure_local_integrity_keys
echo "==> seed_showcase.execute (this takes a minute)"
bench_exec execute crm.demo.seed_showcase.execute

if [ "$SKIP_VERIFY" -eq 0 ]; then
    echo "==> verify"
    bench_exec execute crm.demo.seed_showcase.verify
fi

echo "==> done"
