"""Application command helpers that preserve Student as the operational aggregate."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from crm.fcrm.admissions_application_contract import application_projection
from crm.fcrm.admissions_canonical_contracts import canonical_application_attempt_key
from crm.fcrm.admissions_migration import provenance


def create_application(*, student: str, values: dict[str, Any], expected_revision: int, idempotency_key: str):
	"""Create an application and update only the Student current-state projection.

	The service owns the write boundary.  It never writes Student lifecycle,
	ownership, consent, or master-data fields directly.
	"""
	if not isinstance(values, dict):
		frappe.throw(_("Application values must be an object."), frappe.ValidationError)
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
		return {
			"application": existing,
			"student": student,
			"replayed": True,
			"lifecycle": "human_command_required",
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
	application = frappe.get_doc(application_values).insert(ignore_permissions=True)
	projection = application_projection(application_values)
	if application_values.get("preference") == "Primary":
		for fieldname, value in projection.items():
			student_doc.db_set(fieldname, value, update_modified=False)
	student_doc.db_set("engagement_revision", current_revision + 1, update_modified=False)

	return {
		"application": application.name,
		"student": student,
		"projection": projection,
		"revision": current_revision + 1,
		"replayed": False,
		"lifecycle": "human_command_required",
	}
