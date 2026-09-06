# Cross-repository contract matrix

Frappe CRM is the authority for CRM schema, canonical High School identity,
grants, row scope, revisions, command receipts, interaction identities, and AI
freshness timestamps.
`crm-agents` consumes these contracts and owns the governed agent/runtime
gateway. New cross-repository fields remain optional for at least one release;
incompatible changes require a major version and coordinated deployment.

| Contract | Owner | Version | Consumer | Last aligned |
|---|---|---:|---|---|
| Student intake command | frappe-crm | 1 | crm-agents ingestion | 2026-08-29 |
| Interaction intake command | frappe-crm | 1 | crm-agents conversation | 2026-08-30 |
| Student context event | frappe-crm | 2 | crm-agents decision | 2026-08-30 |
| Score input event | frappe-crm | 1 | crm-agents scoring | 2026-08-30 |
| Score CAS write-back | frappe-crm | 1 | crm-agents scoring | 2026-08-29 |
| CRM Action CAS write-back | frappe-crm | 2 | crm-agents decision | 2026-08-29 |
| Completed Student 360 reader `crm.api.analysis_run_read.get_student_360` | frappe-crm | student-360-read-v1 | crm-agents Next Best Action | 2026-09-01 |
| `settle_analysis_stage` result digest (optional, 64-hex) | frappe-crm | 1 | crm-agents analysis worker | 2026-09-01 |
| AI Insight CAS write-back | frappe-crm | 1 | crm-agents conversation/insight | 2026-08-30 |
| Command Center `/api/cc/*` | crm-agents | cc-v1 | PH-05 frontend | 2026-08-30 |
| School-domain normalized schema and migration | frappe-crm | 1 | School Data panel and import operator | 2026-08-30 |
| School stakeholder endpoint `crm.api.school_domain.get_school_stakeholders` | frappe-crm | 1 | School Data panel | 2026-08-30 |
| School-domain workbook import boundary | frappe-crm | unversioned module contract | External seed/import operator | 2026-08-30 |
| Care-queue read-model `crm.api.student_worklist.list_action_queue` | frappe-crm | action-queue-row-v1 | crm-agents care queue / PH-06 frontend | 2026-09-01 |
| Current-Action claim command `crm.api.student_decision.claim_current_action` | frappe-crm | 1 | crm-agents care queue | 2026-09-01 |
| CRM Action `risk_tier` policy field (`low\|mid\|high`, NOT NULL, Frappe-owned) | frappe-crm | 1 | crm-agents decision / PH-06 frontend | 2026-09-01 |

The `crm/api/agent_events.py` delivery worker reads the crm-agents
`/api/v1/contract-manifest` with a short Frappe cache when the BFF contract
credentials are configured, and falls back to its local compatibility map when
the BFF is unavailable. An unexpected or unsupported event version produces
`AGENT_CONTRACT_VERSION_MISMATCH` and does not crash the delivery loop.

The capability revision also includes the current user's CRM Staff campus and
modified stamp, so scope-sensitive Command Center caches invalidate after a
campus assignment changes.

## Care queue

`list_action_queue` returns current-slot canonical Actions the delegated session
may see (out-of-scope students never appear) with a derived `queue_status`
(`unassigned | claimed | in_progress`), the Frappe-owned `risk_tier`, a
`primary_command`, a `freshness` block, and `can_claim` / `can_approve` /
`can_execute` / `can_reassign`. The `can_*` fields are display hints only — every
dispatch re-checks permission and the Action's `action_revision` /
`decision_revision` server-side regardless of what a row reported.

`claim_current_action(student, expected_revision, idempotency_key,
expected_action, correlation_id?)` is not a wrapper over the decision command.
`expected_action` is **required** — the caller sends the Action name it saw in
the queue row, because a superseded Action and its regenerated replacement can
carry the same `decision_revision` and the slot swap is otherwise undetectable.
The command locks the `CRM Student` row, re-verifies that the current slot still
holds `expected_action`, then compare-and-swaps on `decision_revision`. A slot
that rotated returns `STALE_REVISION` with the fresh `current_action`; two
callers contending the same Action resolve to exactly one `claimed`, the loser
gets `STALE_REVISION` (CAS) or `ALREADY_CLAIMED` if the winner landed first.
Takeover is not allowed: an Action already owned by another Sale returns
`ALREADY_CLAIMED` and is never reassigned. A successful claim bumps
`decision_revision` and `action_revision`, sets `action_owner`, writes a
`CRM Student Decision Event` (`action_reassigned`), and is receipt-idempotent
under its own command-key namespace (a retry replays, it does not re-bump).

Scope widening on claim is deliberately narrow: `assigned_to` is set to the
caller **only when the Student has neither `owner_staff` nor `assigned_to`**
(a raw column write, so `owner_staff` / `owning_team` are not re-derived and an
existing assignee is never displaced). Claiming therefore does **not** grant
execute rights on a Student already owned or assigned to someone else — a caller
outside the owning team is rejected `OUT_OF_SCOPE`, and `can_claim` in the read
model is the real `_valid_executor` rule so the UI does not offer it.

`risk_tier` (`low | mid | high`, `NOT NULL`, fail-closed default `high`) is a
pure function of `action_type` plus structured, controlled generation signals
(tuition or scholarship content, a record-status change, direct-to-applicant or
parent content, a bulk send). It is never derived from attacker-influenced free
text; `package_seed` is a protected field so a client cannot lower the tier by
editing the draft. It is re-derived in `validate()` on every `package_seed` or
`action_type` change; the sole non-controller writer (`edit_email_package`)
re-derives it monotonically — `max(old, computed)` on `low < mid < high`, never
lowered. `CALL` maps to `low` (the human dials; the system only opens the dialer
and shows the advisory script) but `low` is still gated like `mid` — no
auto-execute — until the low-risk execution guarantees hold end to end.

**Lifecycle change:** `deferred → requires-review` is now a legal `CRM Action`
transition (previously the regeneration-failure path raised on a deferred
current Action). A `deferred` Action whose regeneration fails surfaces in the
worklist for review sooner than before.

## School-domain import boundary

`crm/demo/school_domain_import.py` is the boundary for operational workbooks,
which remain outside the repository. `reconcile_school_seed` handles canonical
school rows; `reconcile_ts_workbook` matches annual, stakeholder, and activity
rows to those schools. `seed_school_seed` and `seed_ts_workbook` expose the
write path with `dry_run=True` as the default. Dry runs return reconciliation
reports and an empty mutation set without calling a Frappe write API; explicit
non-dry-run execution is required for writes. Rows that cannot be resolved
without guessing are reported for review, and the report writer excludes raw
workbook rows and contact details.

The normalized school-domain model keeps `CRM High School` as the canonical
persisted school identity, unique by `(province, ward, school_code)`. `CRM
High School Annual Snapshot`, `CRM School Activity`, and `CRM School
Stakeholder` link to that record; snapshot grain is unique by school and
admission year. `CRM Person` is identity-only. `CRM School Stakeholder` is the
many-to-many association between High Schools and People, unique per
`(high_school, person)`, and carries relationship context and portfolio
ownership. A PIC must resolve to `CRM Staff` through `owner_staff`; it is not a
free-text or Person field.

The High School `School Data` panel reads snapshots, school-stakeholder
associations with linked Person identities, and activities; it does not create
a second source of truth. Its stakeholder read uses
`crm.api.school_domain.get_school_stakeholders`, which applies permission-aware
list queries to both the association rows and the returned Person identity
fields.

Promoter access is portfolio-scoped for `CRM School Stakeholder`
and `CRM School Activity` through assigned `owner_staff` or `owning_team`.
`CRM Person` visibility is derived through those associations. Promoters can
read annual snapshots but cannot change snapshot governance; their role policy
also excludes student execution, conversion, lifecycle, and student-ownership
capabilities.

Stakeholder imports require explicit Person approval before creating a new
identity or selecting an existing `CRM Person`; contact details are never used
for an implicit merge. A non-blank workbook PIC that cannot resolve to CRM
Staff remains review-required.

The schema migration runs pre-model-sync. Before legacy relationship fields are
retired, it writes a protected backup of rollback values and a public report
containing counts and record IDs only. Duplicate or missing business keys stop
the migration for manual review. Relationship backfill is savepoint-protected;
the rollback helper rehearses data reversal, while a full schema rollback
requires restoring the protected backup and re-enabling the legacy fields.

## Review-fix invariants

- `upsert_ai_insight` sets both `ai_generated_at` and the legacy required
  `generated_at` at Core apply time. Its `CRM Student Command Receipt` starts
  as `pending`; a retry recovers that receipt, while applied, stale, and failed
  outcomes are settled for replay.
- `interaction_intake` derives `external_id` from
  `source_namespace:source_record_id`. The crm-agents cutover reconciles
  legacy summary hashes and canonical identities; the deployment utility is
  dry-run by default and skips incomplete or colliding identities.
- `CRM Agent Event` is readable by `Sale`, `Lead Sale`, and `Admissions
  Director` (plus `System Manager`) for the delegated, read-only Command
  Center stream. Its delivery lifecycle remains lease-fenced with bounded
  retries/backoff and terminal dead-lettering.
- The Core staleness helper hides AI values for missing/invalid timestamps,
  missing values, stale values, or invalid threshold configuration. Core
  operational metrics remain available.

Runtime verification in a Frappe bench/Docker environment, the production
interaction reconciliation report/apply decision, and staging Command Center
latency remain open deployment gates.

`data_scopes` remain signed manifest metadata in this release. Enforcement is
provided by the delegated Frappe row/field permissions; cohort-level scope
translation is a future phase if product requirements need it.
