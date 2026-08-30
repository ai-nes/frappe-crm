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
