---
title: Production CRM account audit and repair
date: 2026-09-08
branch: main
---

# Production CRM account audit and repair

## Context

Assignment history and team-management requests returned 403 after CRM roles
were reassigned in production. The shared backend path derives profile,
capabilities and organization scope from the authenticated Frappe identity.

## Changes

- Added a read-only `audit_operational_accounts` bench command.
- Audit covers CRM-role users and users linked to `CRM Staff`, including role
  state, capability set, Staff status, organization links and Team membership.
- Added stable issue codes for role, Staff, Department, Campus and Team drift.
- Expanded explicit repair validation to canonical non-Administrator CRM roles.
- `Admissions Director` can be repaired without Staff because it is global; all
  other non-global profiles still require Department and Campus.
- Preserved password, enabled state and privileged accounts. Repair remains
  transactional and fails closed.

## Verification

- Ruff format/check passed.
- Python compile passed.
- Seven focused unit tests passed with a minimal Frappe stub.
- Docker/Frappe integration was unavailable on the host because Docker Desktop
  was not running; production smoke test remains a deployment step.

## Next

Deploy the code, run the read-only audit on the production site, repair only
explicitly approved mappings using existing Department/Campus/Team records,
then test fresh sessions for assignment history, student assignment and team
management.
