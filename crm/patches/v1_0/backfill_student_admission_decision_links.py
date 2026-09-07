"""Move admission-event decision Student links off raw Leads."""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.exists("DocType", "CRM Admission Event Decision"):
		return
	for row in frappe.get_all(
		"CRM Admission Event Decision",
		fields=["name", "student"],
		limit_page_length=0,
		ignore_permissions=True,
	):
		value = row.get("student")
		if not value or frappe.db.exists("CRM Student", value):
			continue
		lead = frappe.db.get_value(
			"CRM Lead", value, ["student", "converted_student"], as_dict=True
		) or {}
		student = lead.get("converted_student") or lead.get("student")
		if student and frappe.db.exists("CRM Student", student):
			frappe.db.set_value(
				"CRM Admission Event Decision",
				row.name,
				"student",
				student,
				update_modified=False,
			)
