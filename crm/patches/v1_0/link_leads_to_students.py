"""Backfill the direct CRM Student to CRM Lead relationship safely."""

from __future__ import annotations

import json

import frappe

INDEX_NAME = "crm_lead_student_idx"


def execute():
	if not frappe.db.exists("DocType", "CRM Lead") or not frappe.db.exists("DocType", "CRM Student"):
		return

	_ensure_index()
	conflicts = []

	if frappe.db.exists("DocType", "CRM Student Contact Conversion"):
		for row in frappe.get_all(
			"CRM Student Contact Conversion",
			fields=["student", "contact"],
			limit_page_length=0,
			ignore_permissions=True,
		):
			_link_lead(row.student, row.contact, conflicts)

	for row in frappe.get_all(
		"CRM Student",
		filters={"student": ["is", "set"]},
		fields=["name", "student"],
		limit_page_length=0,
		ignore_permissions=True,
	):
		_link_lead(row.student, row.name, conflicts)

	if conflicts:
		frappe.log_error(
			message=json.dumps(conflicts, ensure_ascii=False, sort_keys=True),
			title="CRM Lead to Student link conflicts",
		)
	frappe.clear_cache(doctype="CRM Lead")


def _ensure_index():
	if frappe.db.sql("SHOW INDEX FROM `tabCRM Lead` WHERE Key_name = %s", [INDEX_NAME]):
		return
	frappe.db.add_index("CRM Lead", ["student"], index_name=INDEX_NAME)


def _link_lead(lead_name, student_name, conflicts):
	if not lead_name or not student_name:
		return
	if not frappe.db.exists("CRM Lead", lead_name) or not frappe.db.exists("CRM Student", student_name):
		return

	existing = frappe.db.get_value("CRM Lead", lead_name, "student")
	if existing in (None, ""):
		frappe.db.set_value("CRM Lead", lead_name, "student", student_name, update_modified=False)
	elif existing != student_name:
		conflicts.append(
			{
				"lead": lead_name,
				"existing_student": existing,
				"candidate_student": student_name,
			}
		)
