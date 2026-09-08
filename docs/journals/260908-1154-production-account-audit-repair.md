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
- Normalized legacy `CTV-Sale` (and other known legacy membership functions)
  before saving existing Staff records, preventing Frappe Select validation
  failures during repair.

## Verification

- Ruff format/check passed.
- Python compile passed.
- The first production repair attempt rolled back atomically when it found the
  legacy `CTV-Sale` child value; no partial repair remained.
- CI Docker build/push and EC2 deploy passed for commit `78c3dc1`.
- Production audit found 43 accounts and repaired 25 affected accounts.
- Follow-up production audit: 43 healthy, 0 blocking issues, 0 warnings.
- Direct read-only API smoke passed for `sale@gmail.com` and
  `leadsale@gmail.com` on assignment history and team management.
- Production `bench run-tests` was intentionally not enabled because the site
  has `allow_tests` disabled; no production configuration was changed for
  testing.

## Next

Users should sign out and sign in again, then refresh the dashboard pages so
their browser sessions pick up the repaired CRM Staff identity.
