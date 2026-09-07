"""Immutable Student-to-Contact conversion relationship."""

from __future__ import annotations

import frappe
from frappe.model.document import Document

SERVICE_FLAGS = (
	"student_contact_conversion_service",
	"student_conversion_service",
	"student_contact_conversion_migration",
)
CONVERSION_DOCTYPE = "CRM Student Contact Conversion"

INDEXES = (
	(("contact", "converted_at", "name"), "crm_student_contact_conversion_contact_at_idx"),
	(("student_identity", "contact"), "crm_student_contact_conversion_identity_contact_idx"),
)


def _service_write_enabled() -> bool:
	flags = frappe.flags
	return any(getattr(flags, flag, False) for flag in SERVICE_FLAGS)


def _value(row, fieldname):
	if not row:
		return None
	if isinstance(row, dict):
		return row.get(fieldname)
	return getattr(row, fieldname, None)


def on_doctype_update():
	"""Keep the history and identity lookup indexes present after schema sync."""
	for fields, index_name in INDEXES:
		frappe.db.add_index("CRM Student Contact Conversion", list(fields), index_name)


class CRMStudentContactConversion(Document):
	"""Append-only junction; the conversion command is its only writer."""

	def before_validate(self):
		if self.is_new() and not _service_write_enabled():
			frappe.throw(
				"Student Contact conversions must be recorded through the conversion command.",
				frappe.PermissionError,
			)

	def validate(self):
		if not self.is_new():
			frappe.throw(
				"Student Contact conversions are append-only; create a new correction record.",
				frappe.PermissionError,
			)
		self._validate_relationship()

	def _validate_relationship(self):
		student = frappe.db.get_value(
			"CRM Lead",
			self.student,
			["identity", "case_key"],
			as_dict=True,
		)
		if not student:
			frappe.throw("The conversion Student does not exist.", frappe.ValidationError)
		if _value(student, "identity") != self.student_identity:
			frappe.throw("Conversion Student Identity does not match the Student.", frappe.ValidationError)
		if _value(student, "case_key") != self.case_key:
			frappe.throw("Conversion Case Key does not match the Student.", frappe.ValidationError)

		case_key = frappe.db.get_value(
			"CRM Student Case Key",
			self.case_key,
			["identity", "canonical_student"],
			as_dict=True,
		)
		if not case_key:
			frappe.throw("The conversion Case Key does not exist.", frappe.ValidationError)
		if _value(case_key, "identity") != self.student_identity:
			frappe.throw("Conversion Case Key Identity does not match the Student Identity.", frappe.ValidationError)
		if _value(case_key, "canonical_student") != self.student:
			frappe.throw("Conversion Student is not canonical for the Case Key.", frappe.ValidationError)

		contact_identity = frappe.db.get_value("CRM Student", self.contact, "student_identity")
		if not contact_identity:
			frappe.throw("The conversion Contact must have a resolved Student Identity.", frappe.ValidationError)
		if contact_identity != self.student_identity:
			frappe.throw("Conversion Contact Identity does not match the Student Identity.", frappe.ValidationError)

	def on_trash(self):
		frappe.throw("Student Contact conversions are append-only and cannot be deleted.", frappe.PermissionError)


def get_permission_query_conditions(user=None):
	from crm.fcrm.permissions import get_permission_query_conditions as student_conditions

	condition = student_conditions("CRM Lead", user=user)
	if condition is None:
		return None
	if condition == "1=0":
		return "1=0"
	return (
		f"`tab{CONVERSION_DOCTYPE}`.`student` in (select `tabCRM Lead`.`name` "
		f"from `tabCRM Lead` where ({condition}))"
	)


def has_permission(doc, user=None, permission_type=None):
	student = doc.get("student")
	if not student:
		return False
	return bool(frappe.has_permission("CRM Lead", "read", student, user=user))
