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
