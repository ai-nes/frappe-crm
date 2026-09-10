"""Authoritative Lead -> Student conversion command.

Lead owns intake and routing; Student owns the post-conversion care aggregate.
This command is the only workflow that copies the explicit Lead snapshot into a
Student and stamps their direct relationship. Phone, email, and identity are
never used to auto-merge records.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe

from crm.fcrm.conversion_readiness import conversion_readiness
from crm.fcrm.permissions import derive_owner_fields
from crm.fcrm.permissions import has_permission as has_student_permission
from crm.fcrm.record_retention import technical_retention_until
from crm.fcrm.role_policy import capabilities_for_roles
from crm.fcrm.student_feature_flags import enabled

CONVERSION_DOCTYPE = "CRM Student Contact Conversion"
RECEIPT_DOCTYPE = "CRM Student Command Receipt"
CONTACT_DOCTYPE = "CRM Student"
LEAD_DOCTYPE = "CRM Lead"
IDENTITY_DOCTYPE = "CRM Student Identity"
SERVICE_FLAG = "student_conversion_service"
CAPABILITY = "conversion.execute"
POLICY_VERSION = "phase8-conversion-v1"
SCHEMA_VERSION = "phase8-v1"

# Only fields with the same business meaning on both records are copied. Lead
# source attribution, scoring history, academic evidence, identity resolution,
# and operational audit fields remain authoritative on their owning records.
LEAD_TO_STUDENT_FIELDS = (
	("student_name", "full_name"),
	("phone", "phone"),
	("email", "email"),
	("other_email", "other_email"),
	("other_phone", "other_phone"),
	("gender", "gender"),
	("date_of_birth", "date_of_birth"),
	("birth_place", "birth_place"),
	("ethnicity", "ethnicity"),
	("religion", "religion"),
	("nationality", "nationality"),
	("alt_address", "contact_address"),
	("id_number", "id_number"),
	("id_issued_date", "id_issued_date"),
	("id_issued_place", "id_issued_place"),
	("assigned_to", "assigned_to"),
	("owner_staff", "owner_staff"),
	("owning_team", "owning_team"),
	("admission_year", "admission_year"),
	("high_school", "high_school"),
	("province", "province"),
	("ward", "ward"),
	("current_grade", "current_grade"),
	("study_stage", "study_stage"),
	("major", "major"),
	("aspiration", "aspiration"),
	("education_program", "education_program"),
	("branch", "branch"),
	("campaign", "campaign"),
	("source", "source"),
	("alt_name", "parent_name"),
	("alt_phone", "parent_phone"),
	("graduation_score", "graduation_score"),
	("transcript_score", "transcript_score"),
	("english_converted_score", "english_converted_score"),
	("total_score", "total_score"),
	("notes", "notes"),
	("identity", "student_identity"),
)


class StudentConversionError(frappe.ValidationError):
	"""Machine-readable command failure returned by the HTTP adapter."""

	def __init__(self, code: str, message: str):
		self.code = code
		super().__init__(f"{code}: {message}")


def _fail(code: str, message: str):
	raise StudentConversionError(code, message)


def _required(value: Any, label: str) -> str:
	if value is None or not str(value).strip():
		_fail("INVALID_INPUT", f"{label} is required.")
	return str(value).strip()


def _doctype_exists(doctype: str) -> bool:
	try:
		return bool(frappe.db.exists("DocType", doctype))
	except Exception:
		return False


def _fields(doctype: str) -> set[str]:
	try:
		return {field.fieldname for field in frappe.get_meta(doctype).fields}
	except Exception:
		return set()


def _supported_values(doctype: str, values: dict[str, Any]) -> dict[str, Any]:
	"""Keep this command deployable while Phase 8.1 schema sync is rolling out."""
	fields = _fields(doctype)
	return {key: value for key, value in values.items() if key == "doctype" or key in fields}


def _canonical_json(value: Any) -> str:
	return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _fingerprint(payload: dict[str, Any]) -> str:
	return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def conversion_command_key(actor: str, idempotency_key: str) -> str:
	return hashlib.sha256(f"conversion|{actor}|{idempotency_key}".encode()).hexdigest()


def _actor_scope() -> dict[str, Any]:
	actor = getattr(getattr(frappe, "session", None), "user", None)
	if not actor or actor in {"Guest", "None"}:
		_fail("UNAUTHORIZED", "Authentication is required.")
	roles = sorted(frappe.get_roles(actor))
	administrator = actor == "Administrator"
	system_manager = "System Manager" in roles
	capabilities = set(capabilities_for_roles(roles, administrator=administrator))
	if not (administrator or system_manager) and CAPABILITY not in capabilities:
		_fail("FORBIDDEN", "You are not permitted to convert this Student.")
	return {
		"actor": actor,
		"roles": roles,
		"capabilities": sorted(capabilities),
		"administrator": administrator,
		"system_manager": system_manager,
		"capability": CAPABILITY,
		"policy_version": POLICY_VERSION,
	}


def _lock(doctype: str, name: str):
	if not name:
		return
	frappe.db.sql(f"select name from `tab{doctype}` where name = %s for update", (name,))


def _load_student(student_name: str, actor: str, *, internal_service: bool = False):
	if not _doctype_exists("CRM Lead") or not frappe.db.exists("CRM Lead", student_name):
		_fail("NOT_FOUND", "The Student does not exist.")
	student = frappe.get_doc("CRM Lead", student_name)
	# Internal service callers (the assignment batch) authorize the operator once
	# and then commit ownership to another Team.  Re-checking the operator's row
	# scope here would strand every cross-Team Lead as ASSIGNED-never-converted.
	if internal_service:
		return student
	if not has_student_permission(student, user=actor, permission_type="read"):
		_fail("OUT_OF_SCOPE", "The Student is outside the actor's current scope.")
	return student


def _replay(command_key: str, fingerprint: str):
	if not _doctype_exists(RECEIPT_DOCTYPE):
		_fail("CONFIGURATION_ERROR", "Student command receipts are not installed.")
	name = frappe.db.get_value(RECEIPT_DOCTYPE, {"command_key": command_key}, "name")
	if not name:
		return None
	receipt = frappe.get_doc(RECEIPT_DOCTYPE, name)
	if receipt.get("request_fingerprint") not in (None, "", fingerprint):
		_fail("IDEMPOTENCY_KEY_REUSED", "The idempotency key was already used for another request.")
	if receipt.get("outcome") in (None, "", "pending"):
		_fail("RECEIPT_INCOMPLETE", "The previous conversion did not complete; retry with a new key.")
	try:
		result = json.loads(receipt.get("result_json") or "{}")
	except (TypeError, ValueError):
		result = {}
	if not isinstance(result, dict):
		result = {}
	result.setdefault("status", receipt.get("outcome") or "created")
	result["receipt"] = receipt.name
	result["replayed"] = True
	return result


def _receipt_values(
	*,
	command_key: str,
	fingerprint: str,
	student: str,
	actor: str,
	correlation_id: str,
	identity: str | None,
	case_key: str | None,
	scope: dict[str, Any],
	contact: str | None = None,
):
	now = frappe.utils.now_datetime()
	values = {
		"doctype": RECEIPT_DOCTYPE,
		"receipt_key": command_key,
		"command_key": command_key,
		"command_key_version": 1,
		"command_kind": "conversion",
		"request_fingerprint": fingerprint,
		"outcome": "pending",
		"target_student": contact,
		"target_case_key": case_key,
		"target_contact": contact,
		"actor": actor,
		"scope_snapshot": _canonical_json(scope),
		"policy_version": POLICY_VERSION,
		"schema_version": SCHEMA_VERSION,
		"correlation_token": correlation_id,
		"request_received_at": now,
	}
	return _supported_values(RECEIPT_DOCTYPE, values)


def _insert_receipt(**kwargs):
	"""Insert the pending receipt; duplicate keys are handled by replay.

	The caller rechecks ``_replay`` after taking the Student lock.  Letting a
	duplicate insert raise preserves the transaction and lock ownership instead
	of rolling back another request's completed receipt.
	"""
	return frappe.get_doc(_receipt_values(**kwargs)).insert(ignore_permissions=True)


def _complete_receipt(receipt, result: dict[str, Any], outcome: str):
	updates = {
		"outcome": outcome,
		"target_student": result.get("target_student"),
		"result_json": _canonical_json(result),
		"completed_at": frappe.utils.now_datetime(),
		"retention_until": technical_retention_until("receipt"),
		"result_revision": result.get("lifecycle_revision"),
	}
	for fieldname, value in _supported_values(RECEIPT_DOCTYPE, updates).items():
		receipt.db_set(fieldname, value, update_modified=False)


def _identity_and_case(student):
	identity_name = student.get("identity")
	if not identity_name:
		_fail("INTEGRITY_REQUIRED", "Student identity is required for conversion.")
	if not _doctype_exists(IDENTITY_DOCTYPE):
		_fail("CONFIGURATION_ERROR", "Student identity contract is not installed.")
	_lock(IDENTITY_DOCTYPE, identity_name)
	identity = frappe.get_doc(IDENTITY_DOCTYPE, identity_name)
	if identity.get("identity_status") not in (None, "", "active"):
		_fail("INTEGRITY_UNRESOLVED", "Student identity is not active.")
	return identity, None


def _conversion_for_student(student_name: str):
	if not _doctype_exists(CONVERSION_DOCTYPE):
		_fail("CONFIGURATION_ERROR", "Student Contact Conversion is not installed.")
	return frappe.db.get_value(
		CONVERSION_DOCTYPE,
		{"student": student_name},
		["name", "contact", "student_identity", "case_key", "command_receipt"],
		as_dict=True,
	)


def _lock_and_load_contact(contact_name: str):
	_lock(CONTACT_DOCTYPE, contact_name)
	return frappe.get_doc(CONTACT_DOCTYPE, contact_name)


def _resolve_target_student(
	lead, requested_student: str | None, actor: str, *, internal_service: bool = False
):
	linked_student = lead.get("student")
	if linked_student and requested_student and linked_student != requested_student:
		_fail("RELATIONSHIP_CONFLICT", "Lead already points to a different Student.")
	student_name = linked_student or requested_student
	if not student_name:
		return None
	if not frappe.db.exists(CONTACT_DOCTYPE, student_name):
		_fail("NOT_FOUND", "The selected Student does not exist.")
	contact = _lock_and_load_contact(student_name)
	if not internal_service and not has_student_permission(contact, user=actor, permission_type="read"):
		_fail("OUT_OF_SCOPE", "The selected Student is outside the actor's current scope.")
	return contact


def _lead_is_converted(lead) -> bool:
	return bool(lead.get("converted_student"))


def _assert_lead_ownership_ready(lead) -> None:
	"""Require one active responsible Staff before Lead -> Student handoff."""
	owner_staff = str(lead.get("owner_staff") or "").strip()
	assigned_to = str(lead.get("assigned_to") or "").strip()
	owning_team = str(lead.get("owning_team") or "").strip()
	if not owning_team and assigned_to:
		# change_student_ownership commits an owner target with a narrow db update
		# and keeps owning_team empty (it projects pool ownership only). The Team
		# of record is then the one CRM Student itself derives on save, so resolve
		# the same way instead of rejecting every batch-assigned Lead.
		owning_team = str(derive_owner_fields(assigned_to)[1] or "").strip()
	if not owner_staff or not assigned_to or owner_staff != assigned_to or not owning_team:
		_fail(
			"OWNER_REQUIRED",
			"Lead phải có owner_staff, assigned_to và owning_team hợp lệ trước khi tạo Student.",
		)

	staff = frappe.db.get_value(
		"CRM Staff",
		owner_staff,
		["name", "is_active", "user"],
		as_dict=True,
	)
	if not staff or not staff.get("is_active"):
		_fail("OWNER_REQUIRED", "Người phụ trách Lead phải là CRM Staff đang hoạt động.")
	if not staff.get("user") or frappe.db.get_value("User", staff.user, "enabled") not in (1, True, "1"):
		_fail("OWNER_REQUIRED", "Người phụ trách Lead phải có tài khoản User đang hoạt động.")
	if not frappe.db.get_value("CRM Team", {"name": owning_team, "is_active": 1}, "name"):
		_fail("OWNER_REQUIRED", "Team phụ trách Lead phải đang hoạt động.")


def _assert_student_ownership_ready(contact) -> None:
	"""Fail closed if a converted Student has no operational assignee."""
	owner_staff = str(contact.get("owner_staff") or "").strip()
	assigned_to = str(contact.get("assigned_to") or "").strip()
	owning_team = str(contact.get("owning_team") or "").strip()
	if not owner_staff or not assigned_to or owner_staff != assigned_to or not owning_team:
		_fail("OWNER_REQUIRED", "Student bắt buộc phải có người phụ trách và Team sau khi chuyển đổi.")
	if not frappe.db.get_value("CRM Team", {"name": owning_team, "is_active": 1}, "name"):
		_fail("OWNER_REQUIRED", "Team phụ trách Student phải đang hoạt động.")


def _assert_lead_handoff_ready(lead) -> None:
	"""Prevent direct Lead -> Student creation before assignment.

	The public business flow is NEW -> PROCESSING -> PROCESSED -> ASSIGNED,
	then Sale handoff. Legacy converted Leads are allowed through for an
	idempotent status repair, but a fresh Lead cannot create a Student directly.
	"""
	if _lead_is_converted(lead):
		return
	processing_status = str(lead.get("processing_status") or "NEW").upper()
	resolution = str(lead.get("resolution") or "PENDING").upper()
	if "processing_status" not in _fields(LEAD_DOCTYPE):
		_assert_lead_ownership_ready(lead)
		return
	if processing_status != "ASSIGNED" or resolution not in {"MATCHED", "CREATED"}:
		_fail(
			"LEAD_NOT_ASSIGNED",
			"Lead phải ở trạng thái ASSIGNED với resolution MATCHED hoặc CREATED trước khi tạo Student.",
		)
	_assert_lead_ownership_ready(lead)


def _sync_lead_processing_after_conversion(lead, contact, resolution: str) -> None:
	"""Close the Lead only after Student conversion has succeeded."""
	fields = _fields(LEAD_DOCTYPE)
	updates = {}
	if "processing_status" in fields:
		updates["processing_status"] = "CLOSED"
	if "resolution" in fields:
		updates["resolution"] = resolution
	if "resolution_reason" in fields:
		updates["resolution_reason"] = f"{resolution} handoff completed."
	if resolution == "MATCHED" and "matched_student" in fields:
		target_student = contact.name if contact else lead.get("converted_student")
		if target_student:
			updates["matched_student"] = target_student
	if updates:
		frappe.db.set_value(LEAD_DOCTYPE, lead.name, updates, update_modified=False)


def _student_snapshot_values(lead, identity):
	"""Build the one-time Lead -> Student snapshot from an explicit field map."""
	values = {
		"doctype": CONTACT_DOCTYPE,
		"student_identity": identity.name if identity else None,
		"source_lead": lead.get("name"),
		"lead_code": lead.get("lead_code"),
		"converted_at": frappe.utils.now_datetime(),
	}
	for lead_field, student_field in LEAD_TO_STUDENT_FIELDS:
		value = lead.get(lead_field)
		if value not in (None, ""):
			values[student_field] = value
	return _supported_values(CONTACT_DOCTYPE, values)


def _copy_snapshot_to_existing_student(lead, contact, identity):
	values = _student_snapshot_values(lead, identity)
	updates = {}
	for fieldname, value in values.items():
		if fieldname == "doctype" or value in (None, ""):
			continue
		current = contact.get(fieldname)
		if fieldname == "student_identity" and current not in (None, "", value):
			_fail("RELATIONSHIP_CONFLICT", "Selected Student belongs to another Student Identity.")
		if current in (None, ""):
			updates[fieldname] = value
	if not updates:
		return contact
	for fieldname, value in updates.items():
		contact.set(fieldname, value)
	previous = getattr(frappe.flags, SERVICE_FLAG, False)
	setattr(frappe.flags, SERVICE_FLAG, True)
	try:
		contact.save(ignore_permissions=True)
		return contact
	finally:
		setattr(frappe.flags, SERVICE_FLAG, previous)


def _insert_or_reuse_contact(lead, identity, requested_student, actor, *, internal_service: bool = False):
	contact = _resolve_target_student(lead, requested_student, actor, internal_service=internal_service)
	if contact:
		return _copy_snapshot_to_existing_student(lead, contact, identity)
	previous = getattr(frappe.flags, SERVICE_FLAG, False)
	setattr(frappe.flags, SERVICE_FLAG, True)
	try:
		return frappe.get_doc(_student_snapshot_values(lead, identity)).insert(ignore_permissions=True)
	finally:
		setattr(frappe.flags, SERVICE_FLAG, previous)


def _link_lead_to_student(lead, contact, resolution: str):
	if "student" not in _fields(LEAD_DOCTYPE):
		_fail("CONFIGURATION_ERROR", "CRM Lead.student is not installed.")
	linked_student = frappe.db.get_value(LEAD_DOCTYPE, lead.name, "student")
	if linked_student and linked_student != contact.name:
		_fail("RELATIONSHIP_CONFLICT", "Lead already points to a different Student.")
	updates = {
		"student": contact.name,
		"converted_student": contact.name,
		"converted_at": frappe.utils.now_datetime(),
	}
	fields = _fields(LEAD_DOCTYPE)
	for fieldname, value in updates.items():
		if fieldname in fields:
			frappe.db.set_value(LEAD_DOCTYPE, lead.name, fieldname, value, update_modified=False)
	_sync_lead_processing_after_conversion(lead, contact, resolution)


def _lifecycle_event(student_name: str):
	if not _doctype_exists("CRM Student Lifecycle Event"):
		return None
	return frappe.db.get_value(
		"CRM Student Lifecycle Event",
		{"student": student_name, "to_stage": "Enrolled"},
		"name",
		order_by="occurred_at desc, creation desc",
	)


def _conversion_values(student, identity, case, contact, receipt, scope, idempotency_key, correlation_id):
	values = {
		"doctype": CONVERSION_DOCTYPE,
		"lead": student.name,
		"canonical_student": contact.name,
		"student": student.name,
		"student_identity": identity.name,
		"case_key": case.name if case else None,
		"contact": contact.name,
		"lifecycle_event": _lifecycle_event(student.name),
		"actor": scope["actor"],
		"actor_scope": _canonical_json(scope),
		"converted_at": frappe.utils.now_datetime(),
		"command_receipt": receipt.name,
		"idempotency_key": idempotency_key,
		"correlation_id": correlation_id,
		"policy_version": POLICY_VERSION,
		"schema_version": SCHEMA_VERSION,
	}
	return _supported_values(CONVERSION_DOCTYPE, values)


def _result(student, identity, case, contact, conversion, receipt, *, status, replayed, lifecycle_revision):
	return {
		"status": status,
		# ``student`` remains the Lead name for compatibility with the Phase 8
		# response contract. These aliases make the Lead -> Student direction
		# explicit for new clients.
		"student": student.name,
		"lead": student.name,
		"lead_id": student.name,
		"contact": contact.name,
		"target_student": contact.name,
		"student_id": contact.name,
		"conversion": conversion.name if hasattr(conversion, "name") else conversion.get("name"),
		"receipt": receipt.name if hasattr(receipt, "name") else receipt.get("name"),
		"replayed": replayed,
		"lifecycle_revision": lifecycle_revision,
		"student_identity": identity.name,
		"case_key": case.name if case else None,
		"policy_version": POLICY_VERSION,
		"schema_version": SCHEMA_VERSION,
	}


def convert_student(
	student: str,
	expected_lifecycle_revision: Any,
	idempotency_key: str,
	correlation_id: str | None = None,
	target_student: str | None = None,
	_internal_service: bool = False,
):
	"""Convert one Lead into one independent Student snapshot.

	``student`` is the legacy request key for the CRM Lead name. If
	``target_student`` is supplied, it must identify the Student to enrich;
	otherwise the Lead's direct ``student`` link is used, or a new Student is
	created. No weak-identifier matching is performed.

	``_internal_service`` is private to trusted in-process callers (the Lead
	assignment batch) that already authorized the operator and then moved the
	Lead out of that operator's row scope. It never crosses the HTTP boundary:
	the whitelisted adapters pass explicit keyword arguments only.

	A successful conversion closes the Lead and preserves its MATCHED/CREATED
	resolution. Errors roll back the receipt, Student, direct link, and junction
	together; callers should not catch-and-return partial state.
	"""
	if not enabled("conversion_write"):
		_fail("DISABLED", "Student conversion writes are disabled by rollout policy.")
	scope = _actor_scope()
	student_name = _required(student, "student")
	idempotency_key = _required(idempotency_key, "idempotency_key")
	if expected_lifecycle_revision in (None, ""):
		_fail("INVALID_INPUT", "expected_lifecycle_revision is required.")
	correlation_id = _required(correlation_id or frappe.generate_hash(length=20), "correlation_id")
	target_student_name = (
		str(target_student).strip() if target_student and str(target_student).strip() else None
	)
	payload = {
		"student": student_name,
		"expected_lifecycle_revision": str(expected_lifecycle_revision),
	}
	if target_student_name:
		payload["target_student"] = target_student_name
	fingerprint = _fingerprint(payload)
	command_key = conversion_command_key(scope["actor"], idempotency_key)
	# Authorize the current Student before looking up an actor-scoped receipt.
	# Otherwise a user who lost row access could still replay an old result.
	_load_student(student_name, scope["actor"], internal_service=_internal_service)
	lead_doc = frappe.get_doc(LEAD_DOCTYPE, student_name)
	_assert_lead_handoff_ready(lead_doc)
	if _lead_is_converted(lead_doc):
		resolution = str(lead_doc.get("resolution") or "").upper()
		if resolution not in {"MATCHED", "CREATED"}:
			resolution = "CREATED"
		converted_student = lead_doc.get("converted_student") or lead_doc.get("student")
		if not converted_student or not frappe.db.exists("CRM Student", converted_student):
			_fail("OWNER_REQUIRED", "Lead đã chuyển đổi nhưng chưa liên kết CRM Student hợp lệ.")
		_assert_student_ownership_ready(frappe.get_doc("CRM Student", converted_student))
		_sync_lead_processing_after_conversion(lead_doc, None, resolution)
	if replay := _replay(command_key, fingerprint):
		return replay

	try:
		# Fixed lock order: Lead -> Identity -> existing Student. A Lead lock
		# serializes conversion attempts for one intake touchpoint; the direct
		# link, rather than phone/email matching, selects the target Student.
		student_doc = _load_student(student_name, scope["actor"], internal_service=_internal_service)
		_lock(LEAD_DOCTYPE, student_name)
		student_doc = _load_student(student_name, scope["actor"], internal_service=_internal_service)
		_assert_lead_handoff_ready(student_doc)
		# A concurrent retry waits on the aggregate lock.  The winner's committed
		# receipt must be replayed unchanged, never rewritten as ``attached``.
		if replay := _replay(command_key, fingerprint):
			return replay
		readiness = conversion_readiness(student_doc)
		if not readiness["ready"]:
			_fail(
				"CONVERSION_CONDITION_FAILED",
				"Lead is missing conversion requirements: " + ", ".join(readiness["blockers"]),
			)
		try:
			current_revision = int(student_doc.get("lifecycle_revision") or 0)
		except (TypeError, ValueError):
			_fail("INVALID_REVISION", "Student lifecycle revision is invalid.")
		if str(expected_lifecycle_revision) != str(current_revision):
			_fail("STALE_REVISION", "Student lifecycle changed; reload before converting.")
		if student_doc.get("intake_integrity_state") != "resolved":
			_fail("INTEGRITY_UNRESOLVED", "Student intake integrity is not resolved.")
		identity, case = _identity_and_case(student_doc)
		existing_conversion = _conversion_for_student(student_name)
		if existing_conversion:
			if existing_conversion.get("student_identity") not in (None, "", identity.name):
				_fail("INTEGRITY_MISMATCH", "Existing conversion identity does not match Student.")
			if case and existing_conversion.get("case_key") not in (None, "", case.name):
				_fail("INTEGRITY_MISMATCH", "Existing conversion case key does not match Student.")
			if target_student_name and target_student_name != existing_conversion.get("contact"):
				_fail("RELATIONSHIP_CONFLICT", "Lead is already converted to a different Student.")
			contact = _lock_and_load_contact(existing_conversion.get("contact"))
			_assert_student_ownership_ready(contact)
			resolution = str(student_doc.get("resolution") or "").upper()
			if resolution not in {"MATCHED", "CREATED"}:
				resolution = "CREATED"
			_link_lead_to_student(student_doc, contact, resolution)
			receipt = _insert_receipt(
				command_key=command_key,
				fingerprint=fingerprint,
				student=student_name,
				actor=scope["actor"],
				correlation_id=correlation_id,
				identity=identity.name,
				case_key=case.name if case else None,
				scope=scope,
				contact=contact.name,
			)
			result = _result(
				student_doc,
				identity,
				case,
				contact,
				existing_conversion,
				receipt,
				status="attached",
				replayed=False,
				lifecycle_revision=current_revision,
			)
			_complete_receipt(receipt, result, "attached")
			return result

		receipt = _insert_receipt(
			command_key=command_key,
			fingerprint=fingerprint,
			student=student_name,
			actor=scope["actor"],
			correlation_id=correlation_id,
			identity=identity.name,
			case_key=case.name if case else None,
			scope=scope,
		)
		# The receipt can be returned by a concurrent same-key caller only after
		# this transaction commits; it is never a recovery record in pending state.
		contact = _insert_or_reuse_contact(
			student_doc,
			identity,
			target_student_name,
			scope["actor"],
			internal_service=_internal_service,
		)
		_assert_student_ownership_ready(contact)
		resolution = "MATCHED" if target_student_name or student_doc.get("student") else "CREATED"
		_link_lead_to_student(student_doc, contact, resolution)
		conversion_values = _conversion_values(
			student_doc,
			identity,
			case,
			contact,
			receipt,
			scope,
			idempotency_key,
			correlation_id,
		)
		previous = getattr(frappe.flags, SERVICE_FLAG, False)
		setattr(frappe.flags, SERVICE_FLAG, True)
		try:
			# ``contact`` was inserted or locked above in this transaction. Frappe's
			# Link cache can still miss that just-created HS record at this boundary.
			conversion = frappe.get_doc(conversion_values).insert(ignore_permissions=True, ignore_links=True)
		finally:
			setattr(frappe.flags, SERVICE_FLAG, previous)
		result = _result(
			student_doc,
			identity,
			case,
			contact,
			conversion,
			receipt,
			status="created",
			replayed=False,
			lifecycle_revision=current_revision,
		)
		_complete_receipt(receipt, result, "created")
		return result
	except StudentConversionError:
		frappe.db.rollback()
		raise
	except Exception:
		frappe.db.rollback()
		raise
