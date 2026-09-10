"""Move Student-owned concurrency and assignment state off the raw Lead."""

from __future__ import annotations

import frappe

OPERATIONAL_FIELDS = (
	"assigned_to",
	"owning_team",
	"ownership_revision",
	"engagement_revision",
	"lifecycle_revision",
	"student_context_revision",
	"score_input_revision",
	"applied_score_input_revision",
	"applied_policy_revision",
)


def execute():
	if not frappe.db.table_exists("CRM Lead") or not frappe.db.table_exists("CRM Student"):
		return {"status": "skipped", "reason": "student_or_lead_table_missing"}

	student_fields = {field.fieldname for field in frappe.get_meta("CRM Student").fields}
	lead_fields = {field.fieldname for field in frappe.get_meta("CRM Lead").fields}
	copy_fields = [field for field in OPERATIONAL_FIELDS if field in student_fields and field in lead_fields]
	if not copy_fields:
		return {"status": "skipped", "reason": "no_shared_operational_fields"}

	updated = 0
	students = frappe.get_all(
		"CRM Student",
		filters={"source_lead": ["is", "set"]},
		fields=["name", "source_lead", *copy_fields],
		limit_page_length=0,
		ignore_permissions=True,
	)
	for student in students:
		lead = frappe.db.get_value("CRM Lead", student.source_lead, [*copy_fields], as_dict=True)
		if not lead:
			continue
		updates = {
			field: lead.get(field)
			for field in copy_fields
			if student.get(field) in (None, "", 0) and lead.get(field) not in (None, "")
		}
		if updates:
			frappe.db.set_value("CRM Student", student.name, updates, update_modified=False)
			updated += 1

	return {"status": "applied", "students_updated": updated}
