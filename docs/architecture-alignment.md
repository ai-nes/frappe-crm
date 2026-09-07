# Architecture alignment notes

Frappe CRM remains the authority for CRM schema, row scope, revisions, command
receipts, and read models. `crm-agents` reaches those surfaces through named
dotted-method contracts and delegated reads; it does not access the Frappe
database directly.

Controlled CRM vocabularies are Frappe lookup DocTypes keyed by immutable
UPPER_SNAKE `code` values with Vietnamese `display_name` labels. `CRM Term` is
retired; both Contact and Student use the single `enrollment_status` axis, and
the obsolete `lead_status` field is not part of the CRM contract.

The current cross-repository versions and owners are recorded in
[`cross-repo-contract-matrix.md`](cross-repo-contract-matrix.md). Changes to
event or write-back payloads must keep new fields optional for one release and
update that matrix in the same change.

The current implementation also preserves two compatibility rules: AI Insight
write-back stamps both `ai_generated_at` and legacy `generated_at`, and a
`pending` command receipt is recoverable on retry. Interaction intake uses
`source_namespace:source_record_id` as the canonical identity; the companion
reconciliation utility is dry-run by default and never guesses missing or
colliding identities. `CRM Agent Event` read permission is intentionally
granted to the canonical Copilot roles because Command Center `stream` is a
delegated read-only projection.

NBA domain changes use a durable, feature-gated dirty marker on `CRM Student`
instead of creating an evaluation synchronously on the interaction, intent,
or completed-action hot path. The hourly `reconcile_dirty_students` scheduler
drains the oldest markers, uses the existing Student-row lock and evaluation
coalescing rules, and clears a marker only after a successful compare-and-clear;
failed dispatches remain eligible for a later sweep. Once an evaluation is
created, its identity-only `nba.evaluation.requested` delivery contract is
unchanged, so this scheduling change does not require a cross-repository
payload version change.

The school domain keeps `CRM High School` as the canonical persisted school
identity, keyed by the unique `(province, ward, school_code)` combination. The
import boundary may compute `province_code:ward_code:school_code` transiently
for matching, but it does not create a second school identity. It adds `CRM
High School Annual Snapshot` (one row per school and admission year, including
annual New Enter values, derived eligibility, and provenance) and `CRM School
Activity` (dated school relationship work, ownership, outputs, and
provenance).

`CRM Person` is identity-only: name and contact identity are not school
relationship fields. School relationships are many-to-many through `CRM School
Stakeholder`, whose unique `(high_school, person)` association carries the
stakeholder role, position, relationship status, influence, and portfolio
ownership. A Person may therefore be associated with multiple High Schools and
a High School may have multiple People. PIC ownership is Staff-only: `owner_staff`
must resolve to `CRM Staff`; `owning_team` is portfolio metadata, not a Person
or free-text PIC.

The High School record exposes these records, plus permitted linked `CRM Person`
identities, via the user-visible `School Data` panel. The panel calls the
permission-aware `crm.api.school_domain.get_school_stakeholders` endpoint,
which lists permitted stakeholder associations and then permitted Person
identity fields; it is a read projection and does not bypass DocType row scope.
The DocTypes remain the authorities for their data.

External workbooks are handled by `crm/demo/school_domain_import.py` as a
dry-run-first boundary. `reconcile_school_seed` and `reconcile_ts_workbook`
return match status, confidence, and review reasons; `seed_school_seed` and
`seed_ts_workbook` default to `dry_run=True`, return no mutations in that mode,
and require explicit non-dry-run execution for writes. Unresolved, duplicate,
or ambiguous rows remain review-required. A stakeholder row requires explicit
Person approval to create a new `CRM Person` or select an existing Person; the
importer never implicitly merges identities by contact details. A non-blank
workbook PIC must resolve to `CRM Staff`. Reconciliation reports omit raw
workbook rows and contact details.

The schema migration is pre-model-sync: it captures a protected backup of the
legacy relationship values before the old fields are retired, writes a public
counts/IDs-only report, validates duplicate and missing business keys, and
stops for manual review when those checks fail. Relationship backfill runs
behind a savepoint and exposes a rollback rehearsal; a full schema rollback
requires restoring the protected site backup and re-enabling the legacy fields.

Promoter access to school relationship records is a Marketing
portfolio boundary: `CRM School Stakeholder` and `CRM School Activity` rows are limited by
the Promoter's assigned `CRM Staff` owner or team, including direct updates.
`CRM Person` visibility is derived through those associations.
Annual snapshots are read-only to Promoters, while Marketing/Sale and the
governance roles retain their explicit broader access. Promoter capabilities do
not grant student execution, conversion, lifecycle, or student-ownership
operations.

The School-domain schema simplification is complete in the repository. Bench/
Docker checks, production reconciliation and legacy-path deletion approval,
staging latency, and the environment-template deletion gate remain deployment
responsibilities.
