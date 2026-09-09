"""Backfill the canonical Student contact-stage funnel from legacy statuses."""

import frappe

from crm.fcrm.student_stage import stage_from_enrollment_status


def execute():
	"""Populate missing/default CRM Student stages without overwriting progress."""
	meta = frappe.get_meta("CRM Student")
	fieldnames = {field.fieldname for field in meta.fields}
	if "student_stage" not in fieldnames or "enrollment_status" not in fieldnames:
		return

	rows = frappe.get_all(
		"CRM Student",
		fields=["name", "student_stage", "enrollment_status"],
		limit_page_length=0,
	)
	for row in rows:
		if row.get("student_stage") not in (None, "", "New"):
			continue
		frappe.db.set_value(
			"CRM Student",
			row.name,
			"student_stage",
			stage_from_enrollment_status(row.get("enrollment_status")),
			update_modified=False,
		)
