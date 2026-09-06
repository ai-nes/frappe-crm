# Canonical Role and Permission Cutover

## Context

- Date: 2026-09-06
- Scope: local `crm.localhost` and production `crm.faip.pro`
- Commit: `b409164`
- Change type: direct operational cutover; no migration patch

## Canonical CRM roles

The CRM business catalog is now limited to:

1. `CTV Sale`
2. `Sale`
3. `Lead Sale`
4. `Promoter`
5. `Lead Promoter`
6. `Marketing`
7. `Lead Marketing`
8. `Admissions Director`
9. `Administrator`

`System Manager` is retained only as a Frappe technical role internally. It is
not exposed as a CRM Permission Profile or in the CRM user role selector.

## What changed

- Removed legacy CRM roles, profiles, and role-based permission references.
- Normalized legacy naming:
  - `Lead Sales` → `Lead Sale`
  - `CTV-Sale` → `CTV Sale`
  - `Promoter-PR` → `Promoter`
  - `Marketing Lead` → `Lead Marketing`
  - `Marketing Operator` → `Marketing`
  - `Admissions Operations` and `Giám đốc Tuyển sinh` → `Admissions Director`
  - `CEO` → `Administrator`
- Added the canonical permission policy and user role selector behavior.
- Added idempotent account reconciliation for the confirmed production list.
- Accounts outside the confirmed list are assigned `Sale`.
- Technical accounts retain `Administrator` access.
- Local seed/reset flow now reapplies the role cutover and account reconciliation.

## Confirmed production account mapping

| Role | Accounts |
|---|---|
| Admissions Director | `duydt11@fpt.edu.vn`, `trunglb2@fpt.edu.vn` |
| Lead Marketing | `manhtv17@fpt.edu.vn` |
| Lead Promoter | `ngoclh3@fpt.edu.vn` |
| Promoter | `loilq6@fpt.edu.vn`, `danhvt2@fpt.edu.vn`, `dungntt44@fpt.edu.vn`, `dattd4@fpt.edu.vn` |
| Marketing | `nhittt1909@gmail.com` |
| Lead Sale | `tuyendtb@fpt.edu.vn` |
| CTV Sale | `liinhkhanh1810@gmail.com`, `tuyensinhhcm@fpt.edu.vn` |
| Sale | all other non-technical active system users |

Technical accounts intentionally retained with administrator access:

- `Administrator`
- `admin@gmail.com`
- `ngothanhdat4002@gmail.com`
- `nguyenquocan1010@gmail.com`

The `callapi0405_01@gmail.com` account from the source image did not exist on
production, so no account was changed for it.

## Local data

- Local Docker volumes/database were reset as requested.
- Canonical demo data was seeded and verified.
- The local fixture contains four Student records with related contacts,
  interactions, applications, assessments, scoring, AI insights, NBA
  evaluations, and recommendations.

## Production safety

- Production business data was not deleted.
- A production backup was created before the role cutover:
  `20260905_230943`.
- Role/profile verification passed after the cutover with no legacy role or
  profile remaining.

## Reproducibility

After pulling the commit, run:

```bash
task pull
```

For a new local environment, the startup/seed flow applies the same canonical
role cutover and account reconciliation automatically.

## Files added or updated

- `crm/fcrm/role_policy.py`
- `crm/api/user.py`
- `crm/hooks.py`
- `crm/operations_cutover_canonical_roles.py`
- `crm/operations_reconcile_account_roles.py`
- `scripts/cutover_canonical_roles.py`
- `crm/demo/seed_golden_local.py`
- `Taskfile.yml`
- `docker/init.sh`
