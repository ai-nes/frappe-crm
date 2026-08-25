"""Authoritative Student -> Contact conversion command.

Conversion is deliberately a small, server-owned transaction.  The Student
case remains the aggregate being authorized and the Student Identity is the
deduplication boundary; phone and email are observations only.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe

from crm.fcrm.permissions import has_permission as has_student_permission
from crm.fcrm.role_policy import capabilities_for_roles
from crm.fcrm.student_feature_flags import enabled

CONVERSION_DOCTYPE = "CRM Student Contact Conversion"
RECEIPT_DOCTYPE = "CRM Student Command Receipt"
CONTACT_DOCTYPE = "CRM Contact"
IDENTITY_DOCTYPE = "CRM Student Identity"
CASE_KEY_DOCTYPE = "CRM Student Case Key"
SERVICE_FLAG = "student_conversion_service"
CAPABILITY = "conversion.execute"
POLICY_VERSION = "phase8-conversion-v1"
SCHEMA_VERSION = "phase8-v1"


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
	capabilities = set(
		capabilities_for_roles(roles, administrator=administrator)
	)
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


def _load_student(student_name: str, actor: str):
	if not _doctype_exists("CRM Student") or not frappe.db.exists("CRM Student", student_name):
		_fail("NOT_FOUND", "The Student does not exist.")
	student = frappe.get_doc("CRM Student", student_name)
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
		"target_student": student,
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
		"result_json": _canonical_json(result),
		"completed_at": frappe.utils.now_datetime(),
		"result_revision": result.get("lifecycle_revision"),
	}
	for fieldname, value in _supported_values(RECEIPT_DOCTYPE, updates).items():
		receipt.db_set(fieldname, value, update_modified=False)


def _identity_and_case(student):
	identity_name = student.get("identity")
	case_name = student.get("case_key")
	if not identity_name or not case_name:
		_fail("INTEGRITY_REQUIRED", "Student identity and case key are required for conversion.")
	if not _doctype_exists(IDENTITY_DOCTYPE) or not _doctype_exists(CASE_KEY_DOCTYPE):
		_fail("CONFIGURATION_ERROR", "Student identity and case-key contracts are not installed.")
	_lock(IDENTITY_DOCTYPE, identity_name)
	identity = frappe.get_doc(IDENTITY_DOCTYPE, identity_name)
	if identity.get("identity_status") not in (None, "", "active"):
		_fail("INTEGRITY_UNRESOLVED", "Student identity is not active.")
	case = frappe.get_doc(CASE_KEY_DOCTYPE, case_name)
	if case.get("integrity_state") not in (None, "", "resolved"):
		_fail("INTEGRITY_UNRESOLVED", "Student case key is not resolved.")
	if case.get("identity") not in (None, "", identity_name):
		_fail("INTEGRITY_MISMATCH", "Student case key does not prove its identity.")
	if case.get("canonical_student") not in (None, "", student.name):
		_fail("INTEGRITY_MISMATCH", "Student is not the canonical case Student.")
	return identity, case


def _conversion_for_student(student_name: str):
	if not _doctype_exists(CONVERSION_DOCTYPE):
		_fail("CONFIGURATION_ERROR", "Student Contact Conversion is not installed.")
	return frappe.db.get_value(
		CONVERSION_DOCTYPE,
		{"student": student_name},
		["name", "contact", "student_identity", "case_key", "command_receipt"],
		as_dict=True,
	)


def _contacts_for_identity(identity_name: str, student_name: str) -> list[str]:
	"""Find identity-bound Contacts, including provable legacy links only."""
	names: set[str] = set()
	contact_fields = _fields(CONTACT_DOCTYPE)
	if "student_identity" in contact_fields:
		names.update(
		frappe.get_all(
			CONTACT_DOCTYPE,
			filters={"student_identity": identity_name},
			pluck="name",
			ignore_permissions=True,
		)
		or []
	)
	if "student" in contact_fields:
		student_names = frappe.get_all(
			"CRM Student", filters={"identity": identity_name}, pluck="name", ignore_permissions=True
		)
		if student_name not in student_names:
			student_names.append(student_name)
		if student_names:
			names.update(
				frappe.get_all(
					CONTACT_DOCTYPE,
					filters={"student": ["in", student_names]},
					pluck="name",
					ignore_permissions=True,
				)
				or []
			)
	return sorted(names)


def _lock_and_load_contact(contact_name: str):
	_lock(CONTACT_DOCTYPE, contact_name)
	return frappe.get_doc(CONTACT_DOCTYPE, contact_name)


def _resolve_contact(student, identity):
	names = _contacts_for_identity(identity.name, student.name)
	if len(names) > 1:
		_fail("CONTACT_IDENTITY_CONFLICT", "Multiple Contacts are associated with this Student Identity.")
	if not names:
		return None
	contact = _lock_and_load_contact(names[0])
	if contact.get("student_identity") not in (None, "", identity.name):
		_fail("CONTACT_IDENTITY_CONFLICT", "Contact identity does not match the Student Identity.")
	return contact


def _contact_values(student, identity):
	# Only identity-level observations are copied.  Admissions stage, ownership,
	# branch/cycle, SLA and routing fields intentionally stay on the Student case.
	values = {
		"doctype": CONTACT_DOCTYPE,
		"full_name": student.get("student_name"),
		"student_identity": identity.name,
	}
	for fieldname in ("phone", "email"):
		if student.get(fieldname):
			values[fieldname] = student.get(fieldname)
	return _supported_values(CONTACT_DOCTYPE, values)


def _insert_or_reuse_contact(student, identity):
	contact = _resolve_contact(student, identity)
	previous = getattr(frappe.flags, SERVICE_FLAG, False)
	setattr(frappe.flags, SERVICE_FLAG, True)
	try:
		if contact:
			if not contact.get("student_identity") and "student_identity" in _fields(CONTACT_DOCTYPE):
				# This is the only compatibility repair permitted here: a legacy
				# Student link already proved the Contact's identity.
				contact.db_set("student_identity", identity.name, update_modified=False)
			return contact
		return frappe.get_doc(_contact_values(student, identity)).insert(ignore_permissions=True)
	finally:
		setattr(frappe.flags, SERVICE_FLAG, previous)


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
		"student": student.name,
		"student_identity": identity.name,
		"case_key": case.name,
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
		"student": student.name,
		"contact": contact.name,
		"conversion": conversion.name if hasattr(conversion, "name") else conversion.get("name"),
		"receipt": receipt.name if hasattr(receipt, "name") else receipt.get("name"),
		"replayed": replayed,
		"lifecycle_revision": lifecycle_revision,
		"student_identity": identity.name,
		"case_key": case.name,
		"policy_version": POLICY_VERSION,
		"schema_version": SCHEMA_VERSION,
	}


def convert_student(
	student: str,
	expected_lifecycle_revision: Any,
	idempotency_key: str,
	correlation_id: str | None = None,
):
	"""Convert one Enrolled Student case into one identity-level Contact.

	No lifecycle transition is performed.  Errors roll back the receipt,
	Contact, and junction together; callers should not catch-and-return partial
	state.
	"""
	if not enabled("conversion_write"):
		_fail("DISABLED", "Student conversion writes are disabled by rollout policy.")
	scope = _actor_scope()
	student_name = _required(student, "student")
	idempotency_key = _required(idempotency_key, "idempotency_key")
	if expected_lifecycle_revision in (None, ""):
		_fail("INVALID_INPUT", "expected_lifecycle_revision is required.")
	correlation_id = _required(correlation_id or frappe.generate_hash(length=20), "correlation_id")
	payload = {
		"student": student_name,
		"expected_lifecycle_revision": str(expected_lifecycle_revision),
	}
	fingerprint = _fingerprint(payload)
	command_key = conversion_command_key(scope["actor"], idempotency_key)
	# Authorize the current Student before looking up an actor-scoped receipt.
	# Otherwise a user who lost row access could still replay an old result.
	_load_student(student_name, scope["actor"])
	if replay := _replay(command_key, fingerprint):
		return replay

	try:
		# Fixed lock order: Student -> Identity -> existing Contact.  A Student
		# lock serializes cycles for one case; Identity serializes cases for one
		# person before the Contact lookup/create.
		student_doc = _load_student(student_name, scope["actor"])
		_lock("CRM Student", student_name)
		student_doc = _load_student(student_name, scope["actor"])
		# A concurrent retry waits on the aggregate lock.  The winner's committed
		# receipt must be replayed unchanged, never rewritten as ``attached``.
		if replay := _replay(command_key, fingerprint):
			return replay
		if student_doc.get("lifecycle_stage") != "Enrolled":
			_fail("CONVERSION_CONDITION_FAILED", "Only Enrolled Students can be converted.")
		try:
			current_revision = int(student_doc.get("lifecycle_revision") or 0)
		except (TypeError, ValueError):
			_fail("INVALID_REVISION", "Student lifecycle revision is invalid.")
		if str(expected_lifecycle_revision) != str(current_revision):
			_fail("STALE_REVISION", "Student lifecycle changed; reload before converting.")
		if student_doc.get("intake_integrity_state") != "resolved":
			_fail("INTEGRITY_UNRESOLVED", "Student intake integrity is not resolved.")
		identity, case = _identity_and_case(student_doc)
		contact = _resolve_contact(student_doc, identity)
		existing_conversion = _conversion_for_student(student_name)
		if existing_conversion:
			if existing_conversion.get("student_identity") not in (None, "", identity.name):
				_fail("INTEGRITY_MISMATCH", "Existing conversion identity does not match Student.")
			if existing_conversion.get("case_key") not in (None, "", case.name):
				_fail("INTEGRITY_MISMATCH", "Existing conversion case key does not match Student.")
			if not contact or contact.name != existing_conversion.get("contact"):
				contact = _lock_and_load_contact(existing_conversion.get("contact"))
			receipt = _insert_receipt(
				command_key=command_key,
				fingerprint=fingerprint,
				student=student_name,
				actor=scope["actor"],
				correlation_id=correlation_id,
				identity=identity.name,
				case_key=case.name,
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
			case_key=case.name,
			scope=scope,
		)
		# The receipt can be returned by a concurrent same-key caller only after
		# this transaction commits; it is never a recovery record in pending state.
		contact = _insert_or_reuse_contact(student_doc, identity)
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
			conversion = frappe.get_doc(conversion_values).insert(ignore_permissions=True)
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
