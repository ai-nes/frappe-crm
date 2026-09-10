# EC2 deployment

The production flow is intentionally single-node to keep operating cost low:

1. GitHub Actions builds `docker/prod.Dockerfile` and pushes an immutable
   Docker Hub image tagged with the commit SHA.
2. The EC2 host pulls that image and runs the existing production Compose
   stack: CRM, MariaDB, Redis, and Nginx.
3. RDS, Lambda, and Bedrock are not required for this deployment.

## One-time EC2 setup

Create `/opt/frappe-crm/docker/.env` on the server from
`docker/.env.example`. Keep the real passwords only on the server; do not
commit `.env`.

The required site name is `frappe.f-caps.net`. Point its DNS A record to the
EC2 public IP before opening the site. The current Compose stack listens on
HTTP port 80; configure TLS after DNS is working.

## GitHub Actions secrets

Configure these repository or `production` environment secrets:

- `DOCKER_USERNAME`
- `DOCKER_PASSWORD`
- `EC2_HOST`
- `EC2_USER` (`ubuntu`)
- `EC2_SSH_KEY` (the private key matching the EC2 key pair)

The deploy workflow uploads only the Compose file. Application code and all
runtime scripts are already inside the image, so the EC2 host does not build
Frappe during normal deployments.

## Seeding demo data on a server (manual, opt-in)

Deploys run only `bench migrate` — they never seed. To populate the full demo
dataset (all canonical schools + coordinates, exactly 3,184 linked students,
campaigns, edge cases) on a
**demo / staging** deployment, from the compose directory on the server:

```bash
bash scripts/seed-server.sh          # or: COMPOSE_DIR=/opt/frappe-crm bash scripts/seed-server.sh
```

It re-asks for the site name, sets `allow_demo_seed=1` for the run, seeds, then
clears the flag. The shared-password test logins (`seed_role_accounts`) are
skipped on any non-local site. Never run this against a real production site.
