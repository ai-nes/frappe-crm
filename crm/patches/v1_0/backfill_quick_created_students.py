"""Complete metadata for Students created by the pre-contract quick-create route."""

from __future__ import annotations

import frappe


def execute() -> None:
	"""Promote legacy quick-created Student/Lead pairs to canonical records."""
	student_fields = {field.fieldname for field in frappe.get_meta("CRM Student").fields}
	lead_fields = {field.fieldname for field in frappe.get_meta("CRM Lead").fields}
	required_student_fields = {"source_lead", "converted_at", "student_stage"}
	required_lead_fields = {
		"student",
		"converted_student",
		"converted_at",
		"processing_status",
		"resolution",
	}
	if not required_student_fields.issubset(student_fields) or not required_lead_fields.issubset(lead_fields):
		return

	legacy_students = frappe.get_all(
		"CRM Student",
		filters={
			"source_lead": ["is", "set"],
			"converted_at": ["is", "not set"],
			"student_stage": "New",
		},
		fields=["name", "source_lead", "creation"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	for student in legacy_students:
		lead = frappe.db.get_value(
			"CRM Lead",
			student.source_lead,
			["student", "converted_student", "processing_status", "resolution"],
			as_dict=True,
		)
		if not lead or lead.student != student.name or lead.converted_student:
			continue
		if str(lead.processing_status or "NEW").upper() != "NEW":
			continue
		if str(lead.resolution or "PENDING").upper() != "PENDING":
			continue

		frappe.db.set_value(
			"CRM Student",
			student.name,
			"converted_at",
			student.creation,
			update_modified=False,
		)
		frappe.db.set_value(
			"CRM Lead",
			student.source_lead,
			{
				"converted_student": student.name,
				"converted_at": student.creation,
				"processing_status": "CLOSED",
				"resolution": "CREATED",
				"resolution_reason": "CREATED handoff completed.",
			},
			update_modified=False,
		)
