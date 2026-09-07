"""Authoritative Lead processing workflow.

The workflow deliberately keeps intake processing separate from the existing
admissions lifecycle and conversion commands:

    NEW -> PROCESSED -> ASSIGNED -> CLOSED

Email, phone, and province are all required before resolution. Only MATCHED and
CREATED may be assigned; the other four resolutions close the Lead without
creating a Student. Successful handoff delegates conversion to the existing
conversion command and therefore remains fail-closed behind its rollout and
integrity checks.
"""

from __future__ import annotations

from typing import Any

import frappe

from crm.fcrm.student_conversion import StudentConversionError, convert_student
from crm.fcrm.student_intake import normalize_email, normalize_phone
from crm.fcrm.student_ownership import StudentOwnershipError, change_student_ownership
from crm.fcrm.student_stage import StudentStageError, set_student_stage

PROCESSING_STATUSES = ("NEW", "PROCESSED", "ASSIGNED", "CLOSED")
RESOLUTIONS = ("PENDING", "MATCHED", "CREATED", "DUPLICATE", "INVALID", "SPAM", "FAILED")
ADVANCING_RESOLUTIONS = frozenset({"MATCHED", "CREATED"})
TERMINAL_RESOLUTIONS = frozenset({"DUPLICATE", "INVALID", "SPAM", "FAILED"})
SERVICE_FLAG = "lead_processing_service"


class LeadProcessingError(frappe.ValidationError):
	"""Stable machine-readable processing failure."""

	def __init__(self, code: str, message: str):
		self.code = code
		self.error_code = code
		super().__init__(message)


def _fail(code: str, message: str):
	raise LeadProcessingError(code, message)


def _required(value: Any, label: str, *, max_length: int = 255) -> str:
	if value is None or not str(value).strip():
		_fail("INVALID_INPUT", f"{label} is required.")
	value = str(value).strip()
	if len(value) > max_length:
		_fail("INVALID_INPUT", f"{label} is too long.")
	return value


def _reason(value: Any) -> str | None:
	if value in (None, ""):
		return None
	return _required(value, "reason", max_length=500)


def _normalise_province(value: Any) -> str:
	return " ".join(str(value or "").strip().split()).casefold()


def _normalise_identifiers(lead) -> dict[str, str]:
	phone = normalize_phone(lead.get("phone"))
	email = normalize_email(lead.get("email"))
	province = _normalise_province(lead.get("province"))
	blockers: list[str] = []
	if not email:
		blockers.append("missing_or_invalid_email")
	if not phone:
		blockers.append("missing_or_invalid_phone")
	if not province:
		blockers.append("missing_or_invalid_province")
	if blockers:
		_fail("IDENTIFIER_GATE_FAILED", "Email, phone, and province are required before processing.")
	return {"phone": phone, "email": email, "province": province}


def _normalise_row(row: Any) -> dict[str, str]:
	return {
		"phone": normalize_phone(row.get("phone")) or "",
		"email": normalize_email(row.get("email")) or "",
		"province": _normalise_province(row.get("province")),
	}


def _candidate_rows(doctype: str, identifiers: dict[str, str], *, exclude: str | None = None) -> list[Any]:
	filters = []
	for fieldname in ("phone", "email"):
		if identifiers[fieldname]:
			filters.append({fieldname: identifiers[fieldname]})
	if not filters:
		return []
	rows = frappe.get_all(
		doctype,
		or_filters=filters,
		fields=["name", "phone", "email", "province"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	return [row for row in rows if not exclude or row.get("name") != exclude]


def _classify_resolution(lead, identifiers: dict[str, str]) -> tuple[str, str | None]:
	"""Classify only on an exact phone/email/province match."""
	student_matches = _candidate_rows("CRM Student", identifiers)
	exact_students = [row for row in student_matches if _normalise_row(row) == identifiers]
	if len(exact_students) == 1:
		return "MATCHED", exact_students[0].get("name")
	if len(exact_students) > 1:
		return "DUPLICATE", None

	lead_matches = _candidate_rows("CRM Lead", identifiers, exclude=lead.name)
	for row in lead_matches:
		row_identifiers = _normalise_row(row)
		if row_identifiers == identifiers:
			return "DUPLICATE", None
	return "CREATED", None


def _load_lead(lead: str):
	lead_name = _required(lead, "lead")
	try:
		doc = frappe.get_doc("CRM Lead", lead_name)
	except Exception as exc:
		if exc.__class__.__name__ in {"DoesNotExistError", "ValidationError"}:
			_fail("NOT_FOUND", "Lead does not exist.")
		raise
	if not doc.has_permission("write"):
		_fail("FORBIDDEN", "You cannot process this Lead.")
	return doc


def _lock_lead(name: str) -> None:
	frappe.db.sql("select name from `tabCRM Lead` where name=%s for update", (name,))


def _get_status(lead) -> str:
	return str(lead.get("processing_status") or "NEW").strip().upper()


def _get_resolution(lead) -> str:
	return str(lead.get("resolution") or "PENDING").strip().upper()


def _set_processing_values(name: str, values: dict[str, Any]) -> None:
	previous = getattr(frappe.flags, SERVICE_FLAG, False)
	setattr(frappe.flags, SERVICE_FLAG, True)
	try:
		frappe.db.set_value("CRM Lead", name, values, update_modified=True)
	finally:
		setattr(frappe.flags, SERVICE_FLAG, previous)


def process_lead(lead: str, resolution: str | None = None, reason: str | None = None) -> dict[str, Any]:
	"""Validate identifiers and assign one of the six resolutions."""
	lead_doc = _load_lead(lead)
	_lock_lead(lead_doc.name)
	lead_doc = _load_lead(lead_doc.name)
	if _get_status(lead_doc) != "NEW":
		_fail("INVALID_STATUS", "Only NEW Leads can enter processing.")

	try:
		identifiers = _normalise_identifiers(lead_doc)
	except LeadProcessingError:
		validation = {
			"province": bool(_normalise_province(lead_doc.get("province"))),
			"email": bool(normalize_email(lead_doc.get("email"))),
			"phone": bool(normalize_phone(lead_doc.get("phone"))),
		}
		_set_processing_values(
			lead_doc.name,
			{
				"processing_status": "CLOSED",
				"resolution": "INVALID",
				"resolution_reason": "Identifier gate failed.",
			},
		)
		return {
			"status": "CLOSED",
			"resolution": "INVALID",
			"lead": lead_doc.name,
			"validation": validation,
		}

	requested_resolution = str(resolution or "").strip().upper() or None
	if requested_resolution and requested_resolution not in RESOLUTIONS[1:]:
		_fail("INVALID_RESOLUTION", "Resolution must be one of the six supported values.")
	classified_resolution, target_student = _classify_resolution(lead_doc, identifiers)
	final_resolution = requested_resolution or classified_resolution
	if (
		final_resolution in {"MATCHED", "CREATED"}
		and requested_resolution
		and requested_resolution != classified_resolution
	):
		_fail("RESOLUTION_CONFLICT", "Requested resolution does not match identifier classification.")

	status = "PROCESSED" if final_resolution in ADVANCING_RESOLUTIONS else "CLOSED"
	_set_processing_values(
		lead_doc.name,
		{
			"processing_status": status,
			"resolution": final_resolution,
			"resolution_reason": _reason(reason) or f"Resolution: {final_resolution}.",
			"phone": identifiers["phone"],
			"email": identifiers["email"],
			**({"student": target_student} if target_student else {}),
		},
	)
	return {
		"status": status,
		"resolution": final_resolution,
		"lead": lead_doc.name,
		"target_student": target_student,
		"validation": {"email": True, "phone": True, "province": True},
	}


def assign_lead(
	lead: str,
	owner_staff: str,
	target_team_id: str,
	reason: str,
	idempotency_key: str,
	expected_revision: Any,
	correlation_id: str | None = None,
) -> dict[str, Any]:
	"""Assign a processed Lead to a Sale and then move it to ASSIGNED."""
	lead_doc = _load_lead(lead)
	if _get_status(lead_doc) != "PROCESSED" or _get_resolution(lead_doc) not in ADVANCING_RESOLUTIONS:
		_fail("INVALID_STATUS", "Only MATCHED or CREATED Leads in PROCESSED can be assigned.")
	owner_staff = _required(owner_staff, "owner_staff")
	target_team_id = _required(target_team_id, "target_team_id")
	idempotency_key = _required(idempotency_key, "idempotency_key")
	reason = _required(reason, "reason", max_length=2000)
	correlation_id = _required(correlation_id or frappe.generate_hash(length=20), "correlation_id")

	try:
		ownership = change_student_ownership(
			student=lead_doc.name,
			target_kind="owner",
			target_id=owner_staff,
			target_team_id=target_team_id,
			reason=reason,
			idempotency_key=idempotency_key,
			expected_revision=expected_revision,
			correlation_id=correlation_id,
			_commit=False,
		)
		_set_processing_values(lead_doc.name, {"processing_status": "ASSIGNED"})
		frappe.db.commit()
	except (StudentOwnershipError, LeadProcessingError):
		frappe.db.rollback()
		raise
	except Exception:
		frappe.db.rollback()
		raise

	return {
		"status": "ASSIGNED",
		"resolution": _get_resolution(lead_doc),
		"lead": lead_doc.name,
		"ownership": ownership,
	}


def handoff_lead(
	lead: str,
	expected_lifecycle_revision: Any = None,
	idempotency_key: str = "",
	correlation_id: str | None = None,
	target_student: str | None = None,
) -> dict[str, Any]:
	"""Convert an assigned Lead, initialise Student stage, and close the Lead."""
	lead_doc = _load_lead(lead)
	resolution = _get_resolution(lead_doc)
	if _get_status(lead_doc) != "ASSIGNED" or resolution not in ADVANCING_RESOLUTIONS:
		_fail("INVALID_STATUS", "Only assigned MATCHED or CREATED Leads can be handed off.")
	idempotency_key = _required(idempotency_key, "idempotency_key")
	correlation_id = _required(correlation_id or frappe.generate_hash(length=20), "correlation_id")
	if expected_lifecycle_revision in (None, ""):
		expected_lifecycle_revision = lead_doc.get("lifecycle_revision") or 0
	if resolution == "CREATED" and target_student:
		_fail("TARGET_STUDENT_NOT_ALLOWED", "CREATED handoff must create a new Student.")

	if resolution == "MATCHED" and not target_student:
		identifiers = _normalise_identifiers(lead_doc)
		_, target_student = _classify_resolution(lead_doc, identifiers)
		if not target_student:
			_fail("TARGET_STUDENT_REQUIRED", "MATCHED Lead must point to its target Student.")

	try:
		conversion = convert_student(
			student=lead_doc.name,
			expected_lifecycle_revision=expected_lifecycle_revision,
			idempotency_key=idempotency_key,
			correlation_id=correlation_id,
			target_student=target_student,
		)
		student_id = conversion.get("target_student") or conversion.get("student_id")
		if not student_id:
			_fail("CONVERSION_RESULT_INVALID", "Conversion did not return a Student.")
		set_student_stage(student_id, "New", _internal_service=True)
		_set_processing_values(
			lead_doc.name,
			{
				"processing_status": "CLOSED",
				"resolution_reason": f"{resolution} handoff completed.",
			},
		)
		extra = {"status": "CLOSED", "resolution": resolution, "lead": lead_doc.name, "student": student_id}
		frappe.db.commit()
		return {**extra, "conversion": conversion, "student_stage": "New"}
	except StudentStageError as exc:
		frappe.db.rollback()
		_fail(exc.code, str(exc))
	except (StudentConversionError, LeadProcessingError):
		# Conversion errors are intentionally propagated. The Lead remains ASSIGNED
		# and the caller can remediate rollout/integrity prerequisites before retry.
		frappe.db.rollback()
		raise
	except Exception:
		frappe.db.rollback()
		raise
