"""Backfill Student anchors for AI child records after the Student cutover."""

from __future__ import annotations

import frappe


DOCTYPES = (
	"CRM Student Command Receipt",
	"CRM Student Decision Event",
	"CRM Student Assessment",
	"CRM Student Engagement Event",
	"CRM Student Outcome",
	"CRM Student Lifecycle Event",
	"CRM Marketing Engagement",
)


def execute():
	for doctype in DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		fields = {field.fieldname for field in frappe.get_meta(doctype).fields}
		student_field = "target_student" if "target_student" in fields else "student" if "student" in fields else None
		if not student_field:
			continue
		for row in frappe.get_all(
			doctype, fields=["name", student_field], limit_page_length=0, ignore_permissions=True
		):
			value = row.get(student_field)
			if not value or frappe.db.exists("CRM Student", value):
				continue
			lead = frappe.db.get_value(
				"CRM Lead", value, ["student", "converted_student"], as_dict=True
			) or {}
			student = lead.get("converted_student") or lead.get("student")
			if student and frappe.db.exists("CRM Student", student):
				frappe.db.set_value(doctype, row.name, student_field, student, update_modified=False)
