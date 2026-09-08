"""Align converted Student ownership projections with their current Lead assignment."""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.exists("DocType", "CRM Lead") or not frappe.db.exists("DocType", "CRM Student"):
		return

	lead_fields = {field.fieldname for field in frappe.get_meta("CRM Lead").fields}
	student_fields = {field.fieldname for field in frappe.get_meta("CRM Student").fields}
	fields = [
		field
		for field in (
			"name",
			"student",
			"owner_staff",
			"owning_team",
			"owning_pool",
			"assigned_to",
			"ownership_revision",
		)
		if field in lead_fields
	]
	if "student" not in fields:
		return

	for lead in frappe.get_all("CRM Lead", fields=fields, limit_page_length=0, ignore_permissions=True):
		student_name = lead.get("student")
		if not student_name or not frappe.db.exists("CRM Student", student_name):
			continue
		updates = {
			fieldname: lead.get(fieldname)
			for fieldname in ("owner_staff", "owning_team", "owning_pool", "assigned_to")
			if fieldname in student_fields
		}
		if "ownership_revision" in student_fields and "ownership_revision" in lead_fields:
			updates["ownership_revision"] = lead.get("ownership_revision") or 0
		if not updates:
			continue
		current = frappe.db.get_value("CRM Student", student_name, list(updates), as_dict=True) or {}
		if any(current.get(fieldname) != value for fieldname, value in updates.items()):
			frappe.db.set_value("CRM Student", student_name, updates, update_modified=False)

	frappe.db.commit()
