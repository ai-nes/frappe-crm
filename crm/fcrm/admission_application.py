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
	"""Resolve the selected template, falling back for legacy applications."""
	selected = str(getattr(application, "profile_template", None) or "").strip()
	if selected:
		return _get_active_profile_template(selected)
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
			"template_kind": "standard",
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


def _get_active_profile_template(reference: str):
	"""Load an active academic template from either its code or DocType name."""
	template_name = (
		frappe.db.get_value("CRM Admission Profile Template", {"template_code": reference}, "name")
		or reference
	)
	template = frappe.get_doc("CRM Admission Profile Template", template_name)
	if (
		template.status != "Active"
		or template.profile_type != "academic_admission"
		or (template.template_kind or "standard") != "standard"
	):
		frappe.throw(
			_("The selected admission profile template must be active and standard."),
			frappe.ValidationError,
		)
	return template


def _resolve_template_name(reference: str) -> str:
	value = str(reference or "").strip()
	if not value:
		return ""
	return (
		frappe.db.get_value("CRM Admission Profile Template", {"template_code": value}, "name")
		or value
	)


def _active_special_profile_templates(application) -> list[Any]:
	templates = []
	seen = set()
	for option in application.get("special_profile_options") or []:
		reference = str(option.get("special_profile_template") or "").strip()
		template_name = _resolve_template_name(reference)
		if not template_name or template_name in seen:
			continue
		seen.add(template_name)
		template = frappe.get_doc("CRM Admission Profile Template", template_name)
		if (
			template.status != "Active"
			or template.profile_type != "academic_admission"
			or (template.template_kind or "standard") != "special"
		):
			frappe.throw(
				_("Every selected special profile option must be active and special."),
				frappe.ValidationError,
			)
		if template.admission_method and template.admission_method != application.admission_method:
			frappe.throw(
				_("The selected special profile option is not configured for this Admission Method."),
				frappe.ValidationError,
			)
		templates.append(template)
	return templates


def _normalize_special_profile_options(value: Any) -> list[dict[str, Any]]:
	if value in (None, ""):
		return []
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			value = None
	if not isinstance(value, list):
		frappe.throw(_("special_profile_options must be a list."), frappe.ValidationError)

	rows = []
	seen = set()
	for item in value:
		reference = item
		if isinstance(item, dict):
			reference = item.get("special_profile_template") or item.get("profile_template") or item.get("id")
		template_name = _resolve_template_name(str(reference or ""))
		if not template_name:
			frappe.throw(_("A special profile option is required."), frappe.ValidationError)
		if template_name in seen:
			frappe.throw(
				_("A special profile option cannot be selected more than once."),
				frappe.DuplicateEntryError,
			)
		seen.add(template_name)
		rows.append(
			{
				"doctype": "CRM Admission Application Special Profile",
				"special_profile_template": template_name,
				"selection_order": len(rows) + 1,
			}
		)
	return rows


def _get_admission_method_name(reference: str) -> str:
	"""Resolve and validate an active Admission Method reference."""
	method_reference = str(reference or "").strip()
	if not method_reference:
		frappe.throw(_("Admission Method is required."), frappe.ValidationError)
	method_name = (
		frappe.db.get_value("CRM Admission Method", {"code": method_reference}, "name") or method_reference
	)
	method = frappe.db.get_value("CRM Admission Method", method_name, ["name", "enabled"], as_dict=True)
	if not method or not int(method.enabled or 0):
		frappe.throw(_("The selected Admission Method is not active."), frappe.ValidationError)
	return method.name


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


def _resolve_offering(student_doc, application_values: dict[str, Any]) -> None:
	"""Resolve the unique active offering from the Student's admission context."""
	if application_values.get("offering"):
		return

	admission_year = student_doc.admission_year
	admission_method = application_values.get("admission_method")
	if not admission_year or not admission_method:
		frappe.throw(
			_("The Student's Admission Year and Admission Method are required."),
			frappe.ValidationError,
		)
	if application_values.get("admission_year") not in (None, "", admission_year):
		frappe.throw(
			_("Admission Year must be taken from the Student profile."),
			frappe.ValidationError,
		)

	filters = {
		"admission_year": admission_year,
		"admission_method": admission_method,
		"status": "Active",
	}
	if student_doc.branch:
		filters["campus"] = student_doc.branch
	if student_doc.major:
		filters["major"] = student_doc.major

	offerings = frappe.get_all(
		"CRM Admission Offering",
		filters=filters,
		fields=["name", "admission_year"],
		order_by="effective_from desc, name asc",
		limit_page_length=0,
		ignore_permissions=True,
	)
	if len(offerings) != 1:
		frappe.throw(
			_(
				"Could not resolve a unique active Admission Offering for year {0}, "
				"method {1}, campus {2}, and major {3}."
			).format(
				admission_year,
				admission_method,
				student_doc.branch or _("not set"),
				student_doc.major or _("not set"),
			),
			frappe.ValidationError,
		)

	application_values["offering"] = offerings[0].name
	application_values.setdefault("admission_year", offerings[0].admission_year)


def _document_checklist(profile) -> list[dict[str, Any]]:
	"""Project the template junction rows as the Student checklist."""
	from crm.fcrm.student_profile import _condition_applies, _is_checked, _sort_document_type_rows

	checklist = []
	from crm.fcrm.student_profile import _document_type_rows

	for row in _sort_document_type_rows(_document_type_rows(profile)):
		if not row.get("document_type") or not _condition_applies(row, profile):
			continue
		checklist.append(
			{
				"section_code": row.get("section_code") or "general",
				"document_type": row.document_type,
				"requirement_group": row.get("requirement_group") or f"document:{row.document_type}",
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


def _change_profile_template(profile, template, application):
	"""Change the template on the profile owned by this application."""
	profile.db_set("profile_template", template.name, update_modified=False)
	profile.db_set("attempt_key", f"application:{application.name}", update_modified=False)
	profile.db_set("source_reference", application.source_reference, update_modified=True)
	profile.reload()
	return profile


def materialize_admission_profile(application: str | Any) -> dict[str, Any]:
	"""Create or reuse the Student profile and project its document checklist."""
	if isinstance(application, str):
		application = frappe.get_doc("CRM Admission Application", application)
	template = _active_profile_template(application)
	special_templates = _active_special_profile_templates(application)
	profile_name = frappe.db.get_value(
		"CRM Student Admission Profile", {"application": application.name}, "name"
	)
	created = not profile_name
	if profile_name:
		profile = frappe.get_doc("CRM Student Admission Profile", profile_name)
		if profile.profile_template != template.name:
			if profile.profile_status == "Archived":
				frappe.throw(
					_("Archived Student admission profiles cannot change Profile Template."),
					frappe.PermissionError,
				)
			profile = _change_profile_template(profile, template, application)
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
		"special_profile_options": [template.template_code for template in special_templates],
		"document_checklist": _document_checklist(profile),
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
	if not application_values.get("student"):
		frappe.throw(_("Student is required."), frappe.ValidationError)
	_resolve_offering(student_doc, application_values)
	if application_values.get("profile_template"):
		application_values["profile_template"] = _resolve_template_name(application_values["profile_template"])
	if "special_profile_options" in application_values:
		application_values["special_profile_options"] = _normalize_special_profile_options(
			application_values["special_profile_options"]
		)
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


def update_application_preference(*, application: str, preference: str) -> dict[str, Any]:
	"""Update the preference stored on an existing admission application."""
	application_doc = frappe.get_doc("CRM Admission Application", str(application or "").strip())
	student = canonical_student(application_doc.student) or application_doc.student
	student_doc = frappe.get_doc("CRM Student", student)
	if not student_doc.has_permission("write"):
		frappe.throw(
			_("You are not permitted to update this Student's admission application."),
			frappe.PermissionError,
		)

	preference = str(preference or "").strip()
	if preference not in {"Primary", "Alternative"}:
		frappe.throw(
			_("Preference must be Primary or Alternative."),
			frappe.ValidationError,
		)

	preference_order = 1 if preference == "Primary" else 2
	if application_doc.preference != preference:
		application_doc.db_set("preference", preference, update_modified=True)
	if int(application_doc.preference_order or 0) != preference_order:
		application_doc.db_set("preference_order", preference_order, update_modified=False)
	return {
		"application": application_doc.name,
		"student": student,
		"preference": preference,
		"preference_order": preference_order,
	}


def update_application(*, application: str, values: dict[str, Any]) -> dict[str, Any]:
	"""Update the editable admission selection and refresh its Student profile."""
	if not isinstance(values, dict):
		frappe.throw(_("Application values must be an object."), frappe.ValidationError)

	unknown = set(values) - {
		"admission_method",
		"profile_template",
		"preference",
		"special_profile_options",
	}
	if unknown:
		frappe.throw(
			_("Unsupported admission application fields: {0}.").format(", ".join(sorted(unknown))),
			frappe.ValidationError,
		)

	application_doc = frappe.get_doc("CRM Admission Application", str(application or "").strip())
	student = canonical_student(application_doc.student) or application_doc.student
	student_doc = frappe.get_doc("CRM Student", student)
	if not student_doc.has_permission("write"):
		frappe.throw(
			_("You are not permitted to update this Student's admission application."),
			frappe.PermissionError,
		)

	method_name = _get_admission_method_name(
		values.get("admission_method") or application_doc.admission_method
	)
	template_reference = str(values.get("profile_template") or application_doc.profile_template or "").strip()
	if not template_reference:
		frappe.throw(_("Profile Template is required."), frappe.ValidationError)
	template = _get_active_profile_template(template_reference)
	special_options_provided = "special_profile_options" in values
	special_profile_options = (
		_normalize_special_profile_options(values.get("special_profile_options"))
		if special_options_provided
		else None
	)
	if template.admission_method and template.admission_method != method_name:
		frappe.throw(
			_("The selected Profile Template is not configured for this Admission Method."),
			frappe.ValidationError,
		)

	preference = str(values.get("preference") or application_doc.preference or "").strip()
	if preference not in {"Primary", "Alternative"}:
		frappe.throw(_("Preference must be Primary or Alternative."), frappe.ValidationError)
	preference_order = 1 if preference == "Primary" else 2

	target_offering = application_doc.offering
	if method_name != application_doc.admission_method:
		resolved_values = {"admission_method": method_name}
		_resolve_offering(student_doc, resolved_values)
		target_offering = resolved_values["offering"]
		duplicate_application = frappe.db.exists(
			"CRM Admission Application",
			{"student": student, "offering": target_offering, "name": ["!=", application_doc.name]},
		)
		if duplicate_application:
			frappe.throw(
				_("This Student already has an Admission Application for the selected method."),
				frappe.DuplicateEntryError,
			)

	if method_name != application_doc.admission_method or target_offering != application_doc.offering:
		application_doc.db_set("offering", target_offering, update_modified=False)
		application_doc.db_set("admission_method", method_name, update_modified=False)
		application_doc.db_set("major", student_doc.major, update_modified=False)
		application_doc.db_set("campus", student_doc.branch, update_modified=False)
		attempt_key = canonical_application_attempt_key(
			student,
			target_offering,
			application_doc.source_reference or application_doc.source_name or f"student:{student}",
		)
		duplicate_key = frappe.db.exists(
			"CRM Admission Application",
			{"application_attempt_key": attempt_key, "name": ["!=", application_doc.name]},
		)
		if duplicate_key:
			frappe.throw(
				_("Another Admission Application already uses the selected offering."),
				frappe.DuplicateEntryError,
			)
		application_doc.db_set("application_attempt_key", attempt_key, update_modified=False)
		application_doc.db_set(
			"idempotency_fingerprint",
			provenance(
				source_doctype=application_doc.source_doctype or "CRM Student",
				source_name=application_doc.source_name or student,
				source_reference=application_doc.source_reference,
				admission_year=application_doc.admission_year,
				application_attempt_key=attempt_key,
			)["idempotency_fingerprint"],
			update_modified=False,
		)

	application_doc.db_set("profile_template", template.name, update_modified=False)
	application_doc.db_set("preference", preference, update_modified=False)
	application_doc.db_set("preference_order", preference_order, update_modified=True)
	application_doc.reload()
	if special_options_provided:
		application_doc.set("special_profile_options", special_profile_options)
		application_doc.save(ignore_permissions=True)
		application_doc.reload()
	if preference == "Primary":
		student_doc.db_set("admission_method", method_name, update_modified=False)

	materialization = materialize_admission_profile(application_doc)
	return {
		"application": application_doc.name,
		"student": student,
		"admission_method": method_name,
		"preference": preference,
		"preference_order": preference_order,
		"lifecycle": "human_command_required",
		**materialization,
	}
