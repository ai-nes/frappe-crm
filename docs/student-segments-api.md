# Student Segments, Need and Tag — backend contract

## Business sources and scope

Source: `FAIP - Quy định về Tags và Segments.pdf`, supplemented by the retained formal
FAIP Segment & Tag specification and the supplied Need/Tag trees. The Frappe API is the
source of truth for the dashboard integration.

A **Segment** is a saved group of Students selected by criteria. Its `category` is one
of `admission_stage`, `potential`, `intent`, `need`; its `segment_type` is independently
`dynamic` or `static`. Category describes the business use of the group. Overlapping
saved groups do not create additional classifications on the Student.

Segment filters intentionally expose five business dimensions:

| Filter field | Authoritative data | Cardinality |
|---|---|---|
| Student Stage | `CRM Student.student_stage`: New / Attempting / Connected / Qualified / Disqualified | Zero or one; server-managed |
| Potential | `CRM Student.potential`: HIGH / MEDIUM / LOW | Zero or one; unset means unknown |
| Intent | `CRM Student.intent`: HIGH / MEDIUM / LOW | Zero or one, independent of Potential |
| Need | `needs` rows referencing `CRM Need` | Multiple |
| Tag | `tags` rows referencing `CRM Tag` | Multiple |

Need and Tag are contextual classifications in separate dictionaries; they are filter
fields, not additional Segment categories. No automatic scoring thresholds or AI writes are introduced. Existing
`interest_level` and `fit_level` keep their current meanings. `student_stage` remains
server-managed by the existing recruitment lifecycle workflow and is only read by
Segment filters.
Admission Stage edits continue through existing enrollment workflows; the classification
API does not create a competing stage writer or add illustrative stage names to the catalog.

## Authorization and transport

Authenticated Frappe methods use `/api/method/<method>` and the usual `message` response
wrapper. Use POST for mutation methods. Standard Frappe permission and validation exceptions
apply; new business errors contain `INVALID_INPUT`, `REVISION_CONFLICT`,
`INVALID_TRANSITION` or `FORBIDDEN` prefixes where applicable.

Segment owners can manage their own groups within DocPerm. System Manager/Administrator
can manage groups. `is_public` grants read visibility only, never write permission.
Every member query, count, page, and campaign operation applies the caller's current
canonical CRM Student scope and Frappe User Permissions. Public groups cannot expose
out-of-scope Student IDs. Snapshot member records have no independent user permissions.

Need/Tag definition writes require **Administrator session or System Manager**. Sale,
Lead Sale, CTV Sale, Admissions Director and CRM Manager have dictionary read access.
Student classification writes require write access to that Student, including generic
DocType REST/import writes. Server code validates Need/Tag status, prevents duplicates,
and supplies `assigned_by`, `assigned_at`, `source=manual`; clients cannot spoof AI origin.
Changes use Frappe Version history and invalidate the Student context revision.

## Segment methods — `crm.api.student_segment`

| Method | Arguments | Result |
|---|---|---|
| `get_fields` | none | Approved fields, types, options and operators |
| `create_segment` | `data` object | Segment document, status draft, revision 0, and server-generated `segment_code` |
| `get_segment` | `name` | Authorized Segment metadata including `segment_code`, no member IDs |
| `get_segment_by_code` | `segment_code` | Authorized Segment metadata resolved by its immutable `segment_code`, no member IDs |
| `list_segments` | optional status, category, start=0, page_length=20 | Authorized metadata array with `segment_code` and `member_count` |
| `get_segment_analysis` | optional `selected_segment_codes` JSON array, max 5 | Permission-scoped status summary, segment audience counts, overlap cells, and active empty segments |
| `update_segment` | name, data, expected_revision | Updated document |
| `transition_segment` | name, status, expected_revision | Updated document |
| `preview_segment` | segment **or** filters, start=0, page_length=20 | `{total,total_students,start,page_length,students}`; `total` is the filtered count, `total_students` is the permission-scoped Student population, and rows include identity, stage, major, owner and the five classification values |
| `get_segment_audit_logs` | segment, start=0, page_length=50 | Read-only create/update/delete and related activity history for the Segment |
| `delete_segment` | name, expected_revision | `{name,deleted:true}`; unused drafts only |

The Segment detail Task tab uses the existing Task-shaped API with
`reference_doctype="CRM Segment"` and the Segment name as `reference_docname`.
The API persists these rows as `CRM Action Item` records linked through the
`segment` field; it never creates Frappe `Task` records. They are separate from
Student-scoped `CRM Action Item` records, and access follows the Segment's permissions.

Editable fields: title, purpose, responsible_user (enabled User), category, segment_type,
is_public, filters. `segment_code` is generated once on creation in the format
`SEG-YYMMDD-{SHORT_ID}`; `SHORT_ID` is a six-character uppercase alphanumeric
identifier. Legacy codes containing the creator username remain read-compatible.
The code is immutable and unique. Owner, revision and snapshot metadata are server-controlled.
Revision checks and commands lock the document; stale edits fail rather than overwrite.
Title max 140, purpose max 2000. Drafts may be incomplete. Activation requires category,
business purpose, enabled responsible user and valid nonempty filters.

Transitions (literal stored value is **archive**, matching the user request):

- draft → active or archive
- active → inactive or archive
- inactive → active or archive
- archive → terminal, immutable

Only active groups can be attached to campaigns. Type cannot change after publication.
Dynamic rules may be edited while active; previous campaign exposures stay historical.
Static activation captures at most 10,000 currently visible matching Students transactionally.
Reactivation preserves the original snapshot. Captured filters/members cannot be edited;
create another group for a new snapshot. Membership still intersects current access rights.

## Rules

Outer and inner logic can each be `AND` or `OR`, at most 10 groups and 20 conditions
per group. Each group may include a display `name` (at most 140 characters); missing
names default to `Nhóm N`.
Empty groups,
unknown fields/operators, unsupported logic, malformed JSON and non-finite numbers fail.
Numeric operators: `= != > >= < <=`. Select/Link: `= != in not in`. Check: `= !=`.
Need/Tag: `in` means has any listed term; `not in` means has none. Multiple conditions
with `in` implement has-all. Lists contain 1–100 term **names**, not free-text codes.
Existing inactive/archived assignments remain queryable for history. A Need condition
must reference CRM Need and a Tag condition must reference CRM Tag; the record need not
be active to query history.

```json
{
  "title": "Students needing tuition guidance",
  "purpose": "Prioritize tuition counseling",
  "category": "need",
  "segment_type": "dynamic",
  "filters": {
    "logic": "OR",
    "groups": [{"logic": "AND", "name": "Học sinh cần tư vấn học phí", "conditions": [
      {"field": "potential", "operator": "=", "value": "HIGH"},
      {"field": "intent", "operator": "=", "value": "LOW"},
      {"field": "need", "operator": "in", "value": ["<tuition-term-name>"]}
    ]}]
  }
}
```

Approved filter fields are only `student_stage`, `potential`, `intent`, `need` and `tag`. No arbitrary SQL,
arbitrary Student fields or Tag-as-free-text predicates are allowed.
New previews require page_length 1–100 and nonnegative integer start. COUNT and ordered
pagination run in SQL; overlapping branches are deduplicated in SQL.

## Need/Tag methods — `crm.api.student_classification`

| Method | Arguments | Result |
|---|---|---|
| `list_needs` / `list_tags` | status=active, start=0, page_length=50 | Separate dictionary arrays with tag/need details |
| `list_tag_groups` | status=active, start=0, page_length=100 | Tag groups, each containing its detailed Tag records |
| `create_need` / `create_tag` | data: code, label, group (or legacy group_name), description optional | Draft dictionary record |
| `update_need` / `update_tag` | name, data, expected_revision | Updated dictionary record |
| `transition_need` / `transition_tag` | name, status, expected_revision | Updated dictionary record |
| `delete_need` / `delete_tag` | name, expected_revision | Deletes unused, unreferenced draft only |
| `list_need_groups` / `list_tag_group_definitions` | status=active, start=0, page_length=100 | Group master records |
| `create_need_group` / `create_tag_group` | data: code, label, description, sort_order optional | Draft group master record |
| `update_need_group` / `update_tag_group` | name, data, expected_revision | Updated group master record |
| `transition_need_group` / `transition_tag_group` | name, status, expected_revision | Updated group master record |
| `delete_need_group` / `delete_tag_group` | name, expected_revision | Deletes an unused, unreferenced draft group only |
| `get_classifications` | student (canonical CRM Student name) | Student classification projection |
| `update_classifications` | student, data, expected_modified | Updated projection |
| `add_student_tag` | student, tag, expected_modified | Adds one active Tag to the Student; repeated adds are idempotent |
| `remove_student_tag` | student, tag, expected_modified | Removes one Tag; removing an absent Tag is idempotent |
| `update_student_tag` | student, tag, new_tag, expected_modified | Replaces one assigned Tag with another active Tag |

Need, Tag, Need Group and Tag Group records each use the same four lifecycle statuses and
transitions as Segment. Codes are immutable uppercase ASCII `[A-Z][A-Z0-9_]*`, max 100.
Admin can change labels, descriptions and sort order. Need/Tag records link to their
respective group DocType; `group_name` remains a read-compatible legacy mirror in API
payloads. A group cannot be deleted while it contains Need/Tag records.
Reserved Stage/level codes and Potential/Intent/Admission Stage tag codes are rejected;
admins must also review naming meaningfully so tags do not duplicate structured fields.
Archive is read-only. Deactivation never silently removes an existing Student assignment.

`update_classifications.data` supports potential, intent, needs, tags. Omitted keys are
unchanged. needs/tags are replacement arrays of term names for that kind; `[]` clears it.
Use null/empty string to clear a level. Max 100 total unique assignments. Only active
Need/Tag records can be newly assigned; retained inactive/archived records keep their
original assignment metadata.

```json
{
  "student": "<CRM Student name>",
  "expected_modified": "<modified from get_classifications>",
  "data": {
    "potential": "HIGH",
    "intent": "LOW",
    "needs": ["<active-need-name>"],
    "tags": ["<active-tag-name>"]
  }
}
```

Projection: `{student,modified,admission_stage,potential,intent,needs,tags}`. Need rows link
to `CRM Need`; Tag rows link to `CRM Tag`, each with assigned_by, assigned_at and source.
Use list_needs/list_tags with all statuses to render historical assignments.

`list_tag_groups` returns an array shaped as
`[{"group_name": "<group>", "tags": [<Tag record>, ...]}]`; each Tag record includes
`name`, `code`, `label`, `group_name`, `description`, `status`, and `revision`.
Student Tag CRUD requires the current `modified` value as `expected_modified`, checks the
Student write permission, and preserves assignment provenance. Updating a Student Tag
means replacing its assignment; editing the shared Tag definition remains the separate
`update_tag` operation.

The former shared classification records have been migrated and retired. New code uses
separate `CRM Need`, `CRM Tag`, `CRM Student Need Assignment`, and
`CRM Student Tag Assignment` records.

## Migration and compatibility

`crm.patches.v1_0.upgrade_student_segments` is registered in patches.txt and after_install.
Run normal `bench --site <site> migrate` when deploying. Schema changes use DocType JSON.
Legacy groups lacking responsible_user become inactive for review; owner, filters and
campaign references are preserved. New category/purpose are not fabricated for old groups.
Indexes cover status/type, Need/Tag status/group and separate assignment term/parent;
snapshots have a unique (segment,student) constraint. Reruns preserve admin-edited
dictionary records.
35 template terms from the supplied trees are seeded as draft: 23 Needs, 12 Tags. Admin
must activate desired records before staff assignment. Existing shared classifications are
copied into their matching separate dictionary/assignment records before the legacy
DocTypes and hidden Student field are removed; no auto-activation occurs.

Legacy `crm.api.segment` helper names and preview `{contacts}` envelope are preserved;
legacy page_length remains clamped to 100. Legacy saved rules now obey explicit AND/OR
validation and the five-field allowlist. Campaign attach rechecks active state/revision and
permissions each batch. It preserves existing idempotency and historical engagements.
The existing attribution boundary still skips standalone Students without a linked legacy
Lead (`skipped_unresolved_student`); this feature does not migrate campaign attribution.

Local-only remnants of the earlier, superseded implementation (CRM Student Segment,
CRM Student Need and old columns) are not dropped or consumed. They are not part of this
contract. No destructive data reset is required. The main dashboard consumes these methods
through its Segment API service and query hooks; it does not keep a parallel mock store.
