"""Backfill the Lead/Student ownership fields for the admissions core model."""

from __future__ import annotations

import json

import frappe

from crm.fcrm.conversion_readiness import conversion_readiness
from crm.fcrm.student_reference import canonical_student

CANONICAL_CHILD_DOCTYPES = (
	"CRM Interaction",
	"CRM Interaction Evidence",
	"CRM Intent",
	"CRM Score History",
	"CRM Student Analysis Run",
	"CRM Student Assessment",
	"CRM NBA Evaluation",
	"CRM Action Item",
	"Task",
	"CRM Admission Application",
)


def execute():
	if not _doctype_exists("CRM Lead") or not _doctype_exists("CRM Student"):
		return

	lead_fields = _fields("CRM Lead")
	student_fields = _fields("CRM Student")
	_backfill_student_source(lead_fields, student_fields)
	_conversion_readiness(lead_fields)
	_backfill_conversion_aliases()
	_backfill_child_student_links()
	frappe.clear_cache(doctype="CRM Lead")
	frappe.clear_cache(doctype="CRM Student")


def _doctype_exists(doctype: str) -> bool:
	return bool(frappe.db.exists("DocType", doctype))


def _fields(doctype: str) -> set[str]:
	return {field.fieldname for field in frappe.get_meta(doctype).fields}


def _conversion_readiness(lead_fields: set[str]):
	fields = ["name", "id_number", "high_school", "major"]
	if "student" in lead_fields:
		fields.append("student")
	if "converted_student" in lead_fields:
		fields.append("converted_student")
	if "lead_status" in lead_fields:
		fields.append("lead_status")
	if "conversion_status" in lead_fields:
		fields.append("conversion_status")
	if "conversion_blockers" in lead_fields:
		fields.append("conversion_blockers")

	for lead in frappe.get_all("CRM Lead", fields=fields, limit_page_length=0, ignore_permissions=True):
		readiness = conversion_readiness(lead)
		updates = {}
		converted_student = lead.get("student") or lead.get("converted_student")
		if "conversion_status" in lead_fields:
			updates["conversion_status"] = "Converted" if converted_student else readiness["status"]
		if "conversion_blockers" in lead_fields:
			updates["conversion_blockers"] = json.dumps(readiness["blockers"], ensure_ascii=False)
		if "lead_status" in lead_fields:
			updates["lead_status"] = "Converted" if converted_student else (lead.get("lead_status") or "New")
		for fieldname, value in updates.items():
			frappe.db.set_value("CRM Lead", lead.name, fieldname, value, update_modified=False)


def _backfill_student_source(lead_fields: set[str], student_fields: set[str]):
	if "source_lead" not in student_fields:
		return

	student_by_lead = {}
	conversion_doctype = "CRM Student Contact Conversion"
	if _doctype_exists(conversion_doctype):
		for row in frappe.get_all(
			conversion_doctype,
			fields=["student", "contact", "converted_at"],
			limit_page_length=0,
			ignore_permissions=True,
		):
			if row.get("student") and row.get("contact"):
				student_by_lead[row.student] = row

	legacy_fields = ["name", "student"]
	for row in frappe.get_all(
		"CRM Student", fields=legacy_fields, limit_page_length=0, ignore_permissions=True
	):
		if row.get("student") and row.student not in student_by_lead:
			student_by_lead[row.student] = {"student": row.student, "contact": row.name}

	student_by_contact = {
		conversion.get("contact"): (lead, conversion)
		for lead, conversion in student_by_lead.items()
		if conversion.get("contact")
	}
	for lead_name, conversion in student_by_lead.items():
		contact = conversion.get("contact")
		if not contact or not frappe.db.exists("CRM Lead", lead_name):
			continue
		lead = (
			frappe.db.get_value("CRM Lead", lead_name, ["student", "converted_student"], as_dict=True) or {}
		)
		updates = {}
		if "student" in lead_fields and not lead.get("student"):
			updates["student"] = contact
		if "converted_student" in lead_fields and not lead.get("converted_student"):
			updates["converted_student"] = contact
		if "converted_at" in lead_fields and conversion.get("converted_at"):
			updates["converted_at"] = conversion.get("converted_at")
		if "lead_status" in lead_fields and not lead.get("lead_status"):
			updates["lead_status"] = "Converted"
		for fieldname, value in updates.items():
			frappe.db.set_value("CRM Lead", lead_name, fieldname, value, update_modified=False)
	student_fields_to_read = ["name", "source_lead"]
	for student in frappe.get_all(
		"CRM Student",
		fields=student_fields_to_read,
		limit_page_length=0,
		ignore_permissions=True,
	):
		if student.source_lead:
			continue
		lead_and_conversion = student_by_contact.get(student.name)
		if not lead_and_conversion:
			continue
		lead_name, conversion = lead_and_conversion
		if not lead_name or not frappe.db.exists("CRM Lead", lead_name):
			continue
		updates = {"source_lead": lead_name}
		lead = frappe.db.get_value(
			"CRM Lead",
			lead_name,
			["lead_code", "id_number", "id_issued_date", "id_issued_place"],
			as_dict=True,
		)
		for fieldname in ("lead_code", "id_number", "id_issued_date", "id_issued_place"):
			if fieldname in student_fields and lead and lead.get(fieldname):
				updates[fieldname] = lead[fieldname]
		if "converted_at" in student_fields:
			converted_at = conversion.get("converted_at")
			if converted_at:
				updates["converted_at"] = converted_at
		for fieldname, value in updates.items():
			frappe.db.set_value("CRM Student", student.name, fieldname, value, update_modified=False)


def _backfill_child_student_links():
	for doctype in CANONICAL_CHILD_DOCTYPES:
		if not _doctype_exists(doctype):
			continue
		fields = _fields(doctype)
		canonical_field = (
			"crm_student" if "crm_student" in fields else "crm_contact" if "crm_contact" in fields else None
		)
		if not canonical_field or "student" not in fields:
			continue
		for row in frappe.get_all(
			doctype,
			fields=["name", "student", canonical_field],
			limit_page_length=0,
			ignore_permissions=True,
		):
			if row.get(canonical_field):
				continue
			student = canonical_student(row.get("student"))
			if student:
				frappe.db.set_value(doctype, row.name, canonical_field, student, update_modified=False)


def _backfill_conversion_aliases():
	doctype = "CRM Student Contact Conversion"
	if not _doctype_exists(doctype):
		return
	fields = _fields(doctype)
	read_fields = ["name", "student", "contact"]
	read_fields.extend(fieldname for fieldname in ("lead", "canonical_student") if fieldname in fields)
	for row in frappe.get_all(
		doctype,
		fields=read_fields,
		limit_page_length=0,
		ignore_permissions=True,
	):
		updates = {}
		if "lead" in fields and not row.get("lead") and row.get("student"):
			updates["lead"] = row.student
		if "canonical_student" in fields and not row.get("canonical_student") and row.get("contact"):
			updates["canonical_student"] = row.contact
		for fieldname, value in updates.items():
			frappe.db.set_value(doctype, row.name, fieldname, value, update_modified=False)
