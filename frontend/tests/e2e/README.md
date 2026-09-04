# Lead-processing Playwright suite

The suite is mutation-capable and refuses to run without an explicit disposable-site
guard. It does not seed or reset a site from the browser process.

Required runtime values:

```powershell
$env:PLAYWRIGHT_E2E_ENABLED = '1'
$env:PLAYWRIGHT_BASE_URL = 'http://crm.localhost:8000/crm/'
$env:PLAYWRIGHT_ALLOWED_HOST = 'crm.localhost'
$env:PLAYWRIGHT_EXPECTED_SITE = 'crm.localhost'
$env:PLAYWRIGHT_E2E_USER = 'sale@gmail.com'
$env:PLAYWRIGHT_E2E_PASSWORD = '<site-scoped-fixture-secret>'
$env:PLAYWRIGHT_FIXTURE_MANIFEST = 'E:\path\to\playwright-fixture.json'
$env:PLAYWRIGHT_ASSIGNMENT_MANAGER_USER = 'system-manager@example.com'
$env:PLAYWRIGHT_ASSIGNMENT_MANAGER_PASSWORD = '<site-scoped-fixture-secret>'
$env:PLAYWRIGHT_ASSIGNMENT_SALE_USER = 'auto.sale.a@example.com'
$env:PLAYWRIGHT_ASSIGNMENT_SALE_PASSWORD = '<assignment-demo-site-secret>'
$env:E2E_RUN_ID = 'assignment-local-20260905'
```

The manifest is produced by the site-owned fixture orchestration and must contain
only test identifiers, for example:

```json
{
  "PLAYWRIGHT_DETAIL_STUDENT_ID": "CRM-Student-...",
  "PLAYWRIGHT_DETAIL_SLA_ATTEMPT_ID": "CRM-Student-SLA-Attempt-...",
  "PLAYWRIGHT_LIFECYCLE_STUDENT_ID": "CRM-Student-...",
  "PLAYWRIGHT_LIFECYCLE_EVIDENCE_REF": "interaction:CRM Interaction:...",
  "PLAYWRIGHT_NON_ENROLLED_STUDENT_ID": "CRM-Student-...",
  "PLAYWRIGHT_ENROLLED_STUDENT_ID": "CRM-Student-...",
  "PLAYWRIGHT_ENROLLED_LIFECYCLE_REVISION": "3"
}
```

Provision the disposable site and fixture before starting the frontend, then run:

```powershell
cd frontend
npm run e2e:install
npm run test:e2e
```

Run the project browser tests through the repository's supported test workflow.
Always reset the fixture through its site-owned orchestration after the run. Do not
upload `playwright/.auth`, `test-results`, or reports containing cookies or secrets.

## Current evidence

The suite currently contains 7 tests in 5 files (one auth setup test plus six
lead-processing tests). The recorded guarded smoke run passed 2/2: auth against
`crm.localhost` and the negative intake validation case. That report had the
mutation guard enabled.

The full mutation run has passed 7/7 on the provisioned disposable cohort with
the required server-side flags enabled. The flags were disabled after the run;
immutable audit-row cleanup remains a separate fixture teardown concern. See
`flow-traceability.md` for the branch-by-branch evidence boundary.

`assignment-overview.spec.ts` is an additional guarded manager-to-Sale journey.
It does not seed or reset data from the browser. Seed the local demo first, then
provide the manager and assignment-Sale credentials above and run only that spec
when checking the setup workspace. The test covers batch school mapping, direct
Staff context setup and CRM Student intake-to-routing, with Campus derived from
the Sale user's Staff context.
