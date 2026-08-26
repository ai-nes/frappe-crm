"""Migrate historical CRM Student Task rows into the merged Task doctype.
Phase 2 already moved every write path to Task; CRM Student Task and
CRM Recommendation (V1) stay in place as frozen, read-only history.

Forward-only and idempotent: skips any source row that already has a
migrated Task (matched via `legacy_student_task_name`). Also repoints
CRM Student Task Revision's `task` link (its `options` already targets
`Task` doctype-wide as of Phase 1) from the old CRM Student Task name to
the new migrated Task name, so revision history stays queryable.

The live CURRENT row per student is intentionally NOT flipped to
current_slot='CURRENT' here -- that only happens during the Phase 6 cutover
write-pause window (see `migrate_current_slot_rows` below, run manually via
`bench execute`), so this patch is safe to run on a live site without racing
a concurrent `upsert_student_next_task` write.
"""

from __future__ import annotations

import frappe


_PRIORITY_CASE_MAP = {"low": "Low", "medium": "Medium", "high": "High"}

_DIRECT_FIELDS = (
	"student",
	"source_context_revision",
	"disposition",
	"action_type",
	"objective",
	"policy_version",
	"context_version",
	"worklist_priority_rank",
	"revisit_at",
	"requires_review",
	"review_revision",
	"action_revision",
	"execution_package_version",
	"generation_status",
	"generation_failed_at",
	"generation_failure_reason",
	"generation_idempotency_key",
	"producer_identity",
	"payload_digest",
	"recommendation",
	"sales_action",
	"evidence_references",
	"package_seed",
	"outcome",
	"created_at",
	"accepted_at",
	"completed_at",
	"decision_reason",
	"decision_actor",
	"decision_at",
	"decision_revision",
)


def execute():
	if not frappe.db.table_exists("CRM Student Task"):
		return
	frappe.reload_doc("fcrm", "doctype", "task")
	if frappe.db.table_exists("CRM Student Task Revision"):
		frappe.reload_doc("fcrm", "doctype", "crm_student_task_revision")

	failed = []
	frappe.flags.student_task_command = True
	try:
		for row in frappe.get_all("CRM Student Task", fields=["*"], order_by="creation asc"):
			if frappe.db.exists("Task", {"legacy_student_task_name": row.name}):
				continue
			task = frappe.get_doc(
				{
					"doctype": "Task",
					"legacy_student_task_name": row.name,
					"title": str(row.objective or "Student task (migrated)")[:140],
					"status": row.state,
					"priority": _PRIORITY_CASE_MAP.get(row.priority, "Medium"),
					# Phase 6 cutover flips the live CURRENT row explicitly; every
					# migrated row starts un-current so no uniqueness race here.
					"current_slot": None,
					**{field: row.get(field) for field in _DIRECT_FIELDS},
				}
			)
			savepoint = f"migrate_student_task_{row.name.replace('-', '_')}"
			frappe.db.savepoint(savepoint)
			try:
				task.insert(ignore_permissions=True)
			except Exception:
				# A historical row can fail Task's governed-field invariants
				# (e.g. an old ACT/action_type or state/revisit_at pairing
				# that predates a rule tightened after CRM Student Task was
				# frozen). Roll back only this row's partial writes (e.g. an
				# after_insert assignment side effect) and continue -- one bad
				# row must not abort migration for the rest of the table.
				frappe.db.rollback(save_point=savepoint)
				frappe.log_error(
					title="migrate_student_task_to_task: row failed",
					message=f"CRM Student Task {row.name} failed to migrate:\n{frappe.get_traceback()}",
				)
				failed.append(row.name)
	finally:
		frappe.flags.student_task_command = False

	if failed:
		message = f"migrate_student_task_to_task: {len(failed)} row(s) failed and were skipped: {failed}"
		frappe.logger().warning(message)
		print(message)

	if frappe.db.table_exists("CRM Student Task Revision"):
		frappe.db.sql(
			"""
			UPDATE `tabCRM Student Task Revision` revision
			INNER JOIN `tabTask` migrated ON migrated.legacy_student_task_name = revision.task
			SET revision.task = migrated.name
			"""
		)

	frappe.db.commit()


def migrate_current_slot_rows():
	"""Manual Phase 6 cutover step -- do not add to patches.txt. Run only
	inside the write-pause window:

	    bench --site <site> execute \\
	        crm.patches.v1_0.migrate_student_task_to_task.migrate_current_slot_rows

	Flips a migrated Task's current_slot to CURRENT for any student whose
	CRM Student Task CURRENT row has no live Task already claiming CURRENT --
	a student already regenerated post-cutover keeps their live Task, not the
	historical one.
	"""
	current_rows = frappe.get_all(
		"CRM Student Task",
		filters={"current_slot": "CURRENT"},
		fields=["name", "student"],
	)
	flipped, skipped = [], []
	for row in current_rows:
		if frappe.db.exists("Task", {"student": row.student, "current_slot": "CURRENT"}):
			skipped.append(row.student)
			continue
		migrated_name = frappe.db.get_value("Task", {"legacy_student_task_name": row.name}, "name")
		if not migrated_name:
			skipped.append(row.student)
			continue
		frappe.db.set_value("Task", migrated_name, "current_slot", "CURRENT")
		flipped.append(row.student)
	frappe.db.commit()
	return {"flipped": flipped, "skipped": skipped}
