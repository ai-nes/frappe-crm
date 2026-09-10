"""Application command helpers that preserve Student as the operational aggregate."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from crm.fcrm.admissions_application_contract import application_projection
from crm.fcrm.admissions_canonical_contracts import canonical_application_attempt_key
from crm.fcrm.admissions_migration import provenance
from crm.fcrm.student_reference import canonical_student


def _active_profile_template(application):
	"""Resolve the highest active academic template for an application."""
	if not application.admission_method:
		frappe.throw(
			_("An Admission Method is required before creating the admission profile."),
			frappe.ValidationError,
		)
	student_program = frappe.db.get_value("CRM Student", application.student, "education_program")
	templates = frappe.get_all(
		"CRM Admission Profile Template",
		filters={
			"status": "Active",
			"profile_type": "academic_admission",
			"admission_method": application.admission_method,
		},
		fields=["name", "template_code", "template_name", "version", "education_program"],
		order_by="version desc, modified desc, name asc",
		limit_page_length=0,
		ignore_permissions=True,
	)
	if student_program:
		specific = [row for row in templates if row.education_program == student_program]
		generic = [row for row in templates if not row.education_program]
		templates = specific or generic
	else:
		templates = [row for row in templates if not row.education_program]
	if not templates:
		frappe.throw(
			_("No active admission profile template is configured for method {0} and program {1}.").format(
				application.admission_method, student_program or _("the selected Student")
			),
			frappe.ValidationError,
		)
	return frappe.get_doc("CRM Admission Profile Template", templates[0].name)


def _next_profile_attempt_number(student: str, admission_year: str, template: str) -> int:
	"""Allocate the next profile attempt for one Student/template combination."""
	rows = frappe.get_all(
		"CRM Student Admission Profile",
		filters={
			"student": student,
			"admission_year": admission_year,
			"profile_template": template,
		},
		fields=["attempt_number"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	return max((int(row.attempt_number or 0) for row in rows), default=0) + 1


def _document_checklist(profile, template) -> list[dict[str, Any]]:
	"""Project the template junction rows as the Student checklist."""
	from crm.fcrm.student_profile import _condition_applies, _is_checked, _sort_document_type_rows

	checklist = []
	for row in _sort_document_type_rows(template.get("document_types") or []):
		if not row.get("document_type") or not _condition_applies(row, profile):
			continue
		checklist.append(
			{
				"section_code": row.get("section_code") or "general",
				"document_type": row.document_type,
				"requirement_group": row.get("requirement_group")
				or f"document:{row.document_type}",
				"requirement_mode": str(row.get("requirement_mode") or "ALL").upper(),
				"is_required": _is_checked(row.get("is_required")),
				"min_required": int(row.get("min_required") or 1),
				"quantity": int(row.get("quantity") or 1),
				"order_display": int(row.get("order_display") or 0),
				"condition_key": row.get("condition_key"),
				"instruction": row.get("instruction"),
			}
		)
	return checklist


def materialize_admission_profile(application: str | Any) -> dict[str, Any]:
	"""Create or reuse the Student profile and project its document checklist."""
	if isinstance(application, str):
		application = frappe.get_doc("CRM Admission Application", application)
	template = _active_profile_template(application)
	profile_name = frappe.db.get_value(
		"CRM Student Admission Profile", {"application": application.name}, "name"
	)
	created = not profile_name
	if profile_name:
		profile = frappe.get_doc("CRM Student Admission Profile", profile_name)
	else:
		profile = frappe.get_doc(
			{
				"doctype": "CRM Student Admission Profile",
				"student": application.student,
				"profile_template": template.name,
				"admission_year": application.admission_year,
				"attempt_number": _next_profile_attempt_number(
					application.student, application.admission_year, template.name
				),
				"application": application.name,
				"profile_status": "Draft",
				"enrollment_status": "Not Started",
				"source_reference": application.source_reference,
			}
		).insert(ignore_permissions=True)

	from crm.fcrm.student_profile import refresh_document_completeness

	completeness = refresh_document_completeness(profile.name)
	return {
		"admission_profile": profile.name,
		"profile_created": created,
		"profile_template": template.name,
		"document_checklist": _document_checklist(profile, template),
		"document_completeness": completeness,
	}


def create_application(*, student: str, values: dict[str, Any], expected_revision: int, idempotency_key: str):
	"""Create an application and update only the Student current-state projection.

	The service owns the write boundary.  It never writes Student lifecycle,
	ownership, consent, or master-data fields directly.
	"""
	if not isinstance(values, dict):
		frappe.throw(_("Application values must be an object."), frappe.ValidationError)
	student = canonical_student(student) or str(student or "").strip()
	student_doc = frappe.get_doc("CRM Student", student)
	if not student_doc.has_permission("write"):
		frappe.throw(
			_("You are not permitted to create an application for this Student."), frappe.PermissionError
		)
	application_values = dict(values)
	application_values.setdefault("student", student)
	if not application_values.get("student") or not application_values.get("offering"):
		frappe.throw(_("Student and Admission Offering are required."), frappe.ValidationError)
	application_values.setdefault(
		"source_reference",
		f"{student}:{idempotency_key}",
	)
	application_values.setdefault(
		"application_attempt_key",
		canonical_application_attempt_key(
			application_values["student"],
			application_values["offering"],
			application_values["source_reference"],
		),
	)
	metadata = provenance(
		source_doctype="CRM Student",
		source_name=student,
		source_reference=application_values["source_reference"],
		application_attempt_key=application_values["application_attempt_key"],
	)
	existing = frappe.db.get_value(
		"CRM Admission Application", {"idempotency_fingerprint": metadata["idempotency_fingerprint"]}, "name"
	)
	if existing:
		materialization = materialize_admission_profile(existing)
		return {
			"application": existing,
			"student": student,
			"replayed": True,
			"lifecycle": "human_command_required",
			**materialization,
		}
	current_revision = int(student_doc.get("engagement_revision") or 0)
	if int(expected_revision) != current_revision:
		frappe.throw(
			_("Student data changed; reload before creating the application."), frappe.ValidationError
		)

	application_values.update(
		{
			"doctype": "CRM Admission Application",
			"student": student,
			**metadata,
		}
	)
	previous_service_flag = getattr(frappe.flags, "admission_application_service", False)
	frappe.flags.admission_application_service = True
	try:
		application = frappe.get_doc(application_values).insert(ignore_permissions=True)
	finally:
		frappe.flags.admission_application_service = previous_service_flag
	materialization = materialize_admission_profile(application)
	projection = application_projection(application.as_dict())
	student_projection = dict(projection)
	if "campus" in student_projection and not student_doc.meta.has_field("campus"):
		if student_doc.meta.has_field("branch"):
			student_projection["branch"] = student_projection.pop("campus")
	if application_values.get("preference") == "Primary":
		for fieldname, value in student_projection.items():
			student_doc.db_set(fieldname, value, update_modified=False)
	student_doc.db_set("engagement_revision", current_revision + 1, update_modified=False)

	return {
		"application": application.name,
		"student": student,
		"projection": projection,
		"revision": current_revision + 1,
		"replayed": False,
		"lifecycle": "human_command_required",
		**materialization,
	}
