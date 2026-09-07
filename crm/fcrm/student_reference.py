"""Canonical Lead/Student reference helpers for the admissions core."""

from __future__ import annotations

import frappe

CANONICAL_FIELD = "crm_student"


def student_for_lead(lead: str | None) -> str | None:
	if not lead or not frappe.db.exists("CRM Lead", lead):
		return None
	values = frappe.db.get_value("CRM Lead", lead, ["converted_student", "student"], as_dict=True) or {}
	return values.get("converted_student") or values.get("student")


def lead_for_student(student: str | None) -> str | None:
	if not student or not frappe.db.exists("CRM Student", student):
		return None
	return frappe.db.get_value("CRM Student", student, "source_lead") or frappe.db.get_value(
		"CRM Student", student, "student"
	)


def sync_canonical_student(doc):
	"""Populate the canonical Student link while retaining legacy Lead aliases."""
	has_canonical_field = doc.meta.has_field(CANONICAL_FIELD)
	has_contact_field = doc.meta.has_field("crm_contact")
	has_student_contact_field = doc.meta.has_field("contact")
	if not has_canonical_field and not has_contact_field and not has_student_contact_field:
		return

	student = doc.get(CANONICAL_FIELD) or doc.get("crm_contact") or doc.get("contact")
	lead = doc.get("student")
	if not student and lead:
		student = student_for_lead(lead)
	if not student and doc.doctype == "CRM Intent" and doc.get("interaction"):
		student = frappe.db.get_value("CRM Interaction", doc.interaction, "crm_student")
		if not student:
			student = student_for_lead(frappe.db.get_value("CRM Interaction", doc.interaction, "student"))

	if student and not frappe.db.exists("CRM Student", student):
		frappe.throw(f"Canonical Student {student} does not exist.", frappe.ValidationError)
	if student:
		if has_canonical_field:
			doc.set(CANONICAL_FIELD, student)
		if has_contact_field and not doc.get("crm_contact"):
			doc.set("crm_contact", student)
		if has_student_contact_field and not doc.get("contact"):
			doc.set("contact", student)
		if doc.meta.has_field("student") and not doc.get("student"):
			legacy_lead = lead_for_student(student)
			if legacy_lead:
				doc.set("student", legacy_lead)


def canonical_student(value: str | None) -> str | None:
	"""Resolve either a canonical Student ID or a converted Lead ID."""
	if not value:
		return None
	if frappe.db.exists("CRM Student", value):
		return value
	return student_for_lead(value)
