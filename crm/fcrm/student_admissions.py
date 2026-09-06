"""Permissioned, idempotent admissions actions for CRM Student Detail.

The Student Detail UI deliberately has one write boundary.  This service is a
thin orchestrator over the existing canonical records; it does not introduce a
second activity, campaign, scholarship, task, or scoring model.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
from frappe import _

from crm.fcrm.role_policy import capabilities_for_roles
from crm.fcrm.record_retention import technical_retention_until

RECEIPT_DOCTYPE = "CRM Student Command Receipt"
COMMAND_KIND = "admissions_action"
POLICY_VERSION = "phase1-admissions-action-v1"
SCHEMA_VERSION = "phase1-v1"
SERVICE_FLAG = "student_admissions_service"

ACTION_CAPABILITIES = {
	"digital_signal": "interaction.record",
	"call_attempt": "interaction.record",
	"call_success": "interaction.record",
	"brochure_sent": "interaction.record",
	"major_update": "student.execute",
	"lifecycle_transition": "lifecycle.transition",
	"event_invite": "interaction.record",
	"event_register": "interaction.record",
	"event_checkin": "interaction.record",
	"scholarship_interest": "interaction.record",
	"create_task": "interaction.record",
	"create_insight_note": "interaction.record",
	"assign_counselor": "student.ownership.manage",
}

ALLOWED_ACTIONS = frozenset(ACTION_CAPABILITIES)


class StudentAdmissionsError(frappe.ValidationError):
	"""Machine-readable error returned by the API adapter."""

	def __init__(self, code: str, message: str):
		self.code = code
		super().__init__(message)


def _fail(code: str, message: str):
	raise StudentAdmissionsError(code, message)


def _actor_scope(student: str, action: str) -> dict[str, Any]:
	actor = getattr(getattr(frappe, "session", None), "user", None)
	if not actor or actor in {"Guest", "None"}:
		_fail("UNAUTHORIZED", _("Authentication is required."))
	roles = frappe.get_roles(actor)
	capabilities = capabilities_for_roles(roles, administrator=actor == "Administrator")
	student_doc = frappe.get_doc("CRM Student", student)
	if not student_doc.has_permission("read"):
		_fail("OUT_OF_SCOPE", _("Student is outside your current scope."))
	required = ACTION_CAPABILITIES.get(action)
	if actor != "Administrator" and "System Manager" not in roles and required not in capabilities and "admissions.oversee" not in capabilities:
		_fail("FORBIDDEN", _("You are not permitted to perform this admissions action."))
	if action == "major_update" and not student_doc.has_permission("write"):
		_fail("FORBIDDEN", _("You are not permitted to edit this Student profile."))
	return {
		"actor": actor,
		"roles": sorted(roles),
		"capabilities": sorted(capabilities),
		"student": student,
		"action": action,
	}


def _required(value: Any, field: str, max_length: int = 2000) -> str:
	value = str(value or "").strip()
	if not value:
		_fail("INVALID_INPUT", _("{0} is required.").format(field))
	return value[:max_length]


def _payload(value: Any) -> dict[str, Any]:
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except Exception:
			value = None
	if not isinstance(value, dict):
		_fail("INVALID_INPUT", _("Payload must be an object."))
	return value


def _fingerprint(value: dict[str, Any]) -> str:
	return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _command_key(actor: str, idempotency_key: str) -> str:
	return hashlib.sha256(f"{COMMAND_KIND}|{actor}|{idempotency_key}".encode()).hexdigest()


def _read_receipt(command_key: str, fingerprint: str):
	name = frappe.db.get_value(RECEIPT_DOCTYPE, {"command_key": command_key}, "name")
	if not name:
		return None
	receipt = frappe.get_doc(RECEIPT_DOCTYPE, name)
	if receipt.get("request_fingerprint") != fingerprint:
		_fail("IDEMPOTENCY_KEY_REUSED", _("The idempotency key was already used for another request."))
	try:
		result = json.loads(receipt.get("result_json") or "{}")
	except (TypeError, ValueError):
		result = {}
	result.update({"status": "replayed", "replayed": True, "receipt": receipt.name})
	return result


def _new_receipt(command_key: str, fingerprint: str, student: str, actor: str, correlation_id: str):
	return frappe.get_doc(
		{
			"doctype": RECEIPT_DOCTYPE,
			"receipt_key": command_key,
			"command_key": command_key,
			"command_kind": COMMAND_KIND,
			"request_fingerprint": fingerprint,
			"outcome": "pending",
			"target_student": student,
			"actor": actor,
			"scope_snapshot": {"actor": actor, "student": student},
			"policy_version": POLICY_VERSION,
			"schema_version": SCHEMA_VERSION,
			"correlation_token": correlation_id,
			"request_received_at": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)


def _finish_receipt(receipt, result: dict[str, Any], outcome: str = "created", error_code: str | None = None):
	values = {
		"outcome": outcome,
		"result_json": json.dumps(result, default=str),
		"completed_at": frappe.utils.now_datetime(),
		"retention_until": technical_retention_until("receipt"),
	}
	if error_code:
		values["error_code"] = error_code
	for field, value in values.items():
		receipt.db_set(field, value, update_modified=False)


def _interaction_type(preferred: str = "OUTREACH") -> str:
	if frappe.db.exists("CRM Interaction Type", {"name": preferred, "enabled": 1}):
		return preferred
	name = frappe.db.get_value("CRM Interaction Type", {"enabled": 1}, "name", order_by="sort_order asc, name asc")
	if not name:
		name = frappe.get_doc({"doctype": "CRM Interaction Type", "code": preferred, "display_name": preferred}).insert(ignore_permissions=True).name
	return name


def _insert_interaction(student: str, actor: str, summary: str, notes: str | None, *, interaction_type: str = "OUTREACH", external_id: str | None = None, outcome: str | None = None):
	if external_id:
		existing = frappe.db.get_value("CRM Interaction", {"external_id": external_id}, "name")
		if existing:
			return existing
	doc = frappe.get_doc(
		{
			"doctype": "CRM Interaction",
			"student": student,
			"interaction_type": _interaction_type(interaction_type),
			"interaction_datetime": frappe.utils.now_datetime(),
			"external_id": external_id,
			"actor": actor,
			"summary": _required(summary, "summary"),
			"notes": notes,
			"outcome": outcome,
		}
	).insert(ignore_permissions=True)
	return doc.name


def _call(student_doc, actor: str, data: dict[str, Any], *, success: bool, idempotency_key: str):
	if not student_doc.phone:
		_fail("INVALID_INPUT", _("Student phone is required for a call action."))
	status = "Completed" if success else "No Answer"
	duration = int(data.get("duration") or 60) if success else None
	call = frappe.get_doc(
		{
			"doctype": "Call Log",
			"id": f"admissions:{idempotency_key}"[:140],
			"from": _text(frappe.db.get_value("User", actor, "mobile_no") or frappe.db.get_value("User", actor, "phone") or "Admissions"),
			"to": student_doc.phone,
			"type": "Outgoing",
			"status": status,
			"duration": duration,
			"start_time": frappe.utils.now_datetime(),
			"end_time": frappe.utils.now_datetime() if success else None,
			"reference_doctype": "CRM Student",
			"reference_docname": student_doc.name,
			"caller": actor,
		}
	).insert(ignore_permissions=True)
	interaction = frappe.db.get_value("CRM Interaction", {"reference_doctype": "Call Log", "reference_docname": call.name}, "name")
	if not interaction:
		# The Call Log document hook normally creates this row.  If hooks are
		# disabled during a migration/test, use the same canonical helper and
		# reference fields so the fallback cannot create an unlinked duplicate.
		from crm.fcrm.interaction_log import create_interaction
		interaction = create_interaction(
			interaction_type="CONNECTED" if success else "OUTREACH",
			student=student_doc.name,
			reference_doctype="Call Log",
			reference_docname=call.name,
			actor=actor,
			summary=data.get("summary") or (_("Successful call") if success else _("Call attempt")),
			outcome="Captured" if success else "No Response",
		)
	else:
		frappe.db.set_value("CRM Interaction", interaction, {"summary": data.get("summary") or (_("Successful call") if success else _("Call attempt")), "notes": data.get("notes"), "outcome": "Captured" if success else "No Response"}, update_modified=False)
	return {"call_log": call.name, "interaction": interaction}


def _text(value: Any) -> str:
	return str(value or "").strip()[:140] or "Admissions"


def _communication(student_doc, actor: str, data: dict[str, Any]):
	summary = _required(data.get("summary"), "summary")
	comm = frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"status": "Linked",
			"sent_or_received": "Sent",
			"reference_doctype": "CRM Student",
			"reference_name": student_doc.name,
			"subject": summary,
			"content": data.get("content") or summary,
			"sender": actor,
			"sender_full_name": actor,
			"recipients": student_doc.email or student_doc.phone or actor,
			"communication_date": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)
	interaction = frappe.db.get_value("CRM Interaction", {"reference_doctype": "Communication", "reference_docname": comm.name}, "name")
	if not interaction:
		from crm.fcrm.interaction_log import create_interaction
		interaction = create_interaction(
			interaction_type="OUTREACH",
			student=student_doc.name,
			reference_doctype="Communication",
			reference_docname=comm.name,
			actor=actor,
			summary=summary,
			outcome="Captured",
		)
	return {"communication": comm.name, "interaction": interaction}


def _event_action(student: str, actor: str, action: str, data: dict[str, Any], idempotency_key: str, correlation_id: str):
	from crm.fcrm import student_attribution

	previous = getattr(frappe.flags, SERVICE_FLAG, False)
	previous_scope = getattr(frappe.flags, "student_admissions_scope", None)
	frappe.flags.student_admissions_service = True
	frappe.flags.student_admissions_scope = {"actor": actor, "student": student, "capability": ACTION_CAPABILITIES[action]}
	try:
		event_name = _required(data.get("event"), "event")
		if action == "event_invite":
			if not frappe.db.exists("CRM Event", event_name):
				_fail("NOT_FOUND", _("The event does not exist."))
			interaction = _insert_interaction(student, actor, _("Invited to {0}").format(event_name), data.get("notes"), interaction_type="OUTREACH", external_id=f"admissions:{idempotency_key}:interaction")
			result = {"interaction": interaction}
			if data.get("campaign"):
				result["campaign"] = student_attribution.record_campaign_touchpoint(student=student, crm_campaign=data["campaign"], source="Manual", notes=_("Open Day invitation"), idempotency_key=f"{idempotency_key}:campaign", correlation_id=correlation_id)
			return result
		status = "Checked-in" if action == "event_checkin" else "Registered"
		supersedes = None
		if action == "event_checkin":
			prior = frappe.get_all("CRM Marketing Engagement", filters={"student": student, "engagement_kind": "event_participation", "crm_event": event_name}, fields=["name", "supersedes"], order_by="creation desc", limit_page_length=20)
			active = next((row.name for row in prior if not row.supersedes), None)
			supersedes = active
		event = student_attribution.record_event_participation(student=student, crm_event=event_name, status=status, checked_in_at=frappe.utils.now_datetime() if status == "Checked-in" else None, supersedes=supersedes, idempotency_key=f"{idempotency_key}:event", correlation_id=correlation_id)
		summary = _("Checked-in at {0}").format(event_name) if status == "Checked-in" else _("Registered for {0}").format(event_name)
		interaction = _insert_interaction(student, actor, summary, data.get("notes"), interaction_type="CHECKED_IN" if action == "event_checkin" else "REGISTERED", external_id=f"admissions:{idempotency_key}:interaction")
		return {"event": event, "interaction": interaction}
	finally:
		frappe.flags.student_admissions_service = previous
		frappe.flags.student_admissions_scope = previous_scope


def _structured_note(student_doc, actor: str, data: dict[str, Any]):
	content = data.get("content")
	if isinstance(content, dict):
		content = "\n".join(f"<p><strong>{_text(key)}</strong>: {frappe.utils.escape_html(str(value))}</p>" for key, value in content.items())
	content = _required(content, "content", max_length=10000)
	title = data.get("title")
	if title:
		content = f"<p><strong>{frappe.utils.escape_html(str(title))}</strong></p>{content}"
	note = frappe.get_doc(
		{
			"doctype": "FCRM Note",
			"content": content,
			"reference_doctype": "CRM Student",
			"reference_docname": student_doc.name,
		}
	).insert(ignore_permissions=True)
	return {"note": note.name}


def _dispatch(student_doc, actor: str, action: str, data: dict[str, Any], idempotency_key: str, correlation_id: str):
	if action == "digital_signal":
		signal = _required(data.get("signal"), "signal")
		return {"interaction": _insert_interaction(student_doc.name, actor, signal, data.get("notes"), external_id=f"admissions:{idempotency_key}")}
	if action == "call_attempt":
		return _call(student_doc, actor, data, success=False, idempotency_key=idempotency_key)
	if action == "call_success":
		return _call(student_doc, actor, data, success=True, idempotency_key=idempotency_key)
	if action == "brochure_sent":
		return _communication(student_doc, actor, data)
	if action == "major_update":
		major = _required(data.get("major"), "major")
		if not frappe.db.exists("CRM Major", major):
			_fail("INVALID_INPUT", _("The selected major does not exist."))
		student_doc.major = major
		student_doc.save(ignore_permissions=True)
		return {"student": student_doc.name, "major": major}
	if action == "lifecycle_transition":
		from crm.fcrm.student_lifecycle import request_transition
		return request_transition(student=student_doc.name, target_stage=_required(data.get("to_stage"), "to_stage"), reason=data.get("reason"), expected_revision=int(student_doc.get("lifecycle_revision") or 0), idempotency_key=f"{idempotency_key}:lifecycle", correlation_id=correlation_id)
	if action in {"event_invite", "event_register", "event_checkin"}:
		return _event_action(student_doc.name, actor, action, data, idempotency_key, correlation_id)
	if action == "scholarship_interest":
		interaction = _insert_interaction(student_doc.name, actor, _("Scholarship interest"), data.get("notes"), interaction_type="COUNSELING", external_id=f"admissions:{idempotency_key}:interaction")
		intent_type = data.get("intent_type") or "SCHOLARSHIP"
		if not frappe.db.exists("CRM Intent Type", intent_type):
			_fail("INVALID_INPUT", _("Scholarship intent type is not configured."))
		intent = frappe.get_doc({"doctype": "CRM Intent", "interaction": interaction, "intent_type": intent_type, "intent_role": "Dominant", "polarity": "Positive", "confidence": data.get("confidence"), "notes": data.get("target")}).insert(ignore_permissions=True)
		return {"interaction": interaction, "intent": intent.name}
	if action == "create_task":
		task = frappe.get_doc({"doctype": "Task", "title": _required(data.get("title"), "title"), "description": data.get("description"), "priority": data.get("priority") or "Medium", "status": "Todo", "assigned_to": data.get("assigned_to") or actor, "due_date": data.get("due_date"), "student": student_doc.name, "reference_doctype": "CRM Student", "reference_docname": student_doc.name}).insert(ignore_permissions=True)
		return {"task": task.name}
	if action == "create_insight_note":
		return _structured_note(student_doc, actor, data)
	if action == "assign_counselor":
		from crm.fcrm.student_ownership import change_student_ownership
		counselor = _required(data.get("counselor"), "counselor")
		team = data.get("team")
		if not team:
			memberships = frappe.get_all("CRM Team Membership", filters={"parent": counselor, "parenttype": "CRM Staff"}, fields=["team"], limit_page_length=10)
			teams = sorted({row.get("team") for row in memberships if row.get("team")})
			if len(teams) == 1:
				team = teams[0]
			else:
				_fail("INVALID_INPUT", _("Team is required when the counselor belongs to multiple teams."))
		return change_student_ownership(student=student_doc.name, target_kind="owner", target_id=counselor, target_team_id=team, reason=data.get("reason") or _("Admissions assignment"), idempotency_key=f"{idempotency_key}:ownership", expected_revision=int(student_doc.get("ownership_revision") or 0), correlation_id=correlation_id)
	_fail("INVALID_ACTION", _("Unsupported admissions action."))


def perform_action(*, student: str, action: str, expected_revision: Any, idempotency_key: str, payload: Any = None, correlation_id: str | None = None, occurred_at: Any = None) -> dict[str, Any]:
	student = _required(student, "student", 140)
	action = _required(action, "action", 80)
	if action not in ALLOWED_ACTIONS:
		_fail("INVALID_ACTION", _("Unsupported admissions action."))
	idempotency_key = _required(idempotency_key, "idempotency_key", 140)
	correlation_id = _text(correlation_id or idempotency_key)
	if expected_revision in (None, ""):
		_fail("INVALID_INPUT", _("Expected revision is required."))
	data = _payload(payload)
	if occurred_at in (None, "") and not data.get("occurred_at"):
		_fail("INVALID_INPUT", _("Occurred at is required."))
	data.setdefault("occurred_at", occurred_at)
	scope = _actor_scope(student, action)
	fingerprint = _fingerprint({"student": student, "action": action, "expected_revision": str(expected_revision), "payload": data})
	command_key = _command_key(scope["actor"], idempotency_key)
	if replayed := _read_receipt(command_key, fingerprint):
		return replayed
	try:
		receipt = _new_receipt(command_key, fingerprint, student, scope["actor"], correlation_id)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		# A concurrent request may reserve the same command key between the
		# read and insert.  Roll back the failed insert, then apply the normal
		# fingerprint/replay contract instead of returning a 500.
		frappe.db.rollback()
		if replayed := _read_receipt(command_key, fingerprint):
			return replayed
		raise
	savepoint = f"admissions_action_{frappe.generate_hash(length=8)}"
	frappe.db.savepoint(savepoint)
	try:
		frappe.db.sql("select name from `tabCRM Student` where name = %s for update", (student,))
		student_doc = frappe.get_doc("CRM Student", student)
		current_revision = int(student_doc.get("engagement_revision") or 0)
		if str(expected_revision) != str(current_revision):
			_fail("STALE_REVISION", _("Student activity changed; reload before retrying."))
		result = _dispatch(student_doc, scope["actor"], action, data, idempotency_key, correlation_id)
		new_revision = current_revision + 1
		frappe.db.set_value("CRM Student", student, "engagement_revision", new_revision, update_modified=False)
		result.update({"status": "created", "student": student, "action": action, "revision": new_revision, "receipt": receipt.name, "correlation_id": correlation_id})
		_finish_receipt(receipt, result)
		return result
	except Exception as exc:
		frappe.db.rollback(save_point=savepoint)
		if isinstance(exc, StudentAdmissionsError):
			_finish_receipt(receipt, {"status": "failed", "student": student, "action": action}, outcome="failed", error_code=exc.code)
			raise
		_finish_receipt(receipt, {"status": "failed", "student": student, "action": action}, outcome="failed", error_code="ACTION_FAILED")
		raise


def set_attachment_visibility(*, student: str, file_name: str, is_private: Any, confirm_public: bool = False) -> dict[str, Any]:
	student = _required(student, "student")
	file_name = _required(file_name, "file_name")
	scope = _actor_scope(student, "create_insight_note")
	if not (scope["actor"] == "Administrator" or "System Manager" in scope["roles"] or "admissions.oversee" in scope["capabilities"]):
		_fail("FORBIDDEN", _("Only an admissions supervisor may change document visibility."))
	file_doc = frappe.get_doc("File", file_name)
	if file_doc.attached_to_doctype != "CRM Student" or file_doc.attached_to_name != student:
		_fail("OUT_OF_SCOPE", _("File is not attached to this Student."))
	private_value = str(is_private).strip().lower() not in {"0", "false", "no", "off", ""}
	confirmation = str(confirm_public).strip().lower() in {"1", "true", "yes", "on"}
	if not private_value and not confirmation:
		_fail("CONFIRMATION_REQUIRED", _("Making a Student document public requires confirmation."))
	file_doc.db_set("is_private", 1 if private_value else 0, update_modified=True)
	return {"status": "updated", "student": student, "file": file_name, "is_private": private_value}
