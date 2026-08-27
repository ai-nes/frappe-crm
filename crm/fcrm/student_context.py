"""Permission-scoped Student engagement context read service.

This module is a read model only.  Outcome/lifecycle command services remain
the sole event writers; compatibility Interaction and Enrollment Transition
rows are used only while their legacy-read flag is enabled.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import date, datetime
from typing import Any

import frappe
from frappe import _

from crm.fcrm.qualification import redact_evidence
from crm.fcrm.role_policy import capabilities_for_roles
from crm.fcrm.student_feature_flags import enabled, legacy_read_enabled
from crm.fcrm.student_lifecycle import get_lifecycle_context
from crm.fcrm.attribution import get_student_attribution
from crm.fcrm.student_contact_conversion import conversion_rows_for_student

CONTEXT_POLICY_VERSION = "phase5-context-v1"
MAX_HISTORY_LIMIT = 50
DONE_TASK_STATUSES = {"done", "canceled", "cancelled", "completed"}


def _fields(doctype: str) -> set[str]:
	try:
		return {field.fieldname for field in frappe.get_meta(doctype).fields}
	except Exception:
		return set()


def _exists(doctype: str) -> bool:
	try:
		return bool(frappe.db.table_exists(doctype))
	except Exception:
		return False


def _get(row: Any, *keys: str, default: Any = None) -> Any:
	for key in keys:
		value = row.get(key) if hasattr(row, "get") else getattr(row, key, None)
		if value not in (None, ""):
			return value
	return default


def _json(value: Any) -> Any:
	if isinstance(value, (dict, list)):
		return value
	if isinstance(value, str):
		try:
			return json.loads(value)
		except (TypeError, ValueError):
			return None
	return None


def _text(value: Any, limit: int = 500) -> str | None:
	if value in (None, ""):
		return None
	return str(value).strip()[:limit] or None


def _iso(value: Any) -> str | None:
	return None if value in (None, "") else str(value)


def _can_read_record(doctype: str, name: Any) -> bool:
	"""Check linked-record permission before exposing a context projection."""
	if not name:
		return False
	try:
		return bool(frappe.has_permission(doctype, "read", name))
	except Exception:
		try:
			return bool(frappe.get_doc(doctype, name).has_permission("read"))
		except Exception:
			return False


def _linked_student(row: Any) -> str | None:
	student = _get(row, "student")
	if not student and _get(row, "reference_doctype") == "CRM Student":
		student = _get(row, "reference_docname")
	return student


def _visible_linked_record(doctype: str, name: Any, student: str | None) -> bool:
	if not name or not _can_read_record(doctype, name):
		return False
	if not student:
		return True
	try:
		doc = frappe.get_doc(doctype, name)
		linked = _linked_student(doc)
		if not linked and doc.get("interaction"):
			linked = frappe.db.get_value("CRM Interaction", doc.get("interaction"), "student")
		if not linked and doc.get("attached_to_doctype") == "CRM Student":
			linked = doc.get("attached_to_name")
		return linked == student
	except Exception:
		return False


def _may_read_audit_reason() -> bool:
	actor = getattr(getattr(frappe, "session", None), "user", None)
	if actor == "Administrator":
		return True
	try:
		return "student.audit.reason.read" in capabilities_for_roles(frappe.get_roles(actor))
	except Exception:
		return False


def _limit(value: int | str | None) -> int:
	try:
		value = 20 if value in (None, "") else int(value)
	except (TypeError, ValueError):
		frappe.throw(_("history_limit must be an integer."), frappe.ValidationError)
	if not 1 <= value <= MAX_HISTORY_LIMIT:
		frappe.throw(_("history_limit must be between 1 and {0}.").format(MAX_HISTORY_LIMIT), frappe.ValidationError)
	return value


def _secret() -> bytes:
	try:
		from frappe.utils.password import get_encryption_key

		return f"crm-student-context:{get_encryption_key()}".encode()
	except Exception:
		return b"crm-student-context"


def _cursor(student: str, item: dict[str, Any]) -> str:
	payload = {"student": student, "policy": CONTEXT_POLICY_VERSION, "at": str(item.get("occurred_at") or ""), "name": str(item.get("name") or "")}
	body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
	sig = hmac.new(_secret(), body, hashlib.sha256).digest()
	return ".".join(base64.urlsafe_b64encode(part).rstrip(b"=").decode() for part in (body, sig))


def _verify_cursor(token: str | None, student: str) -> tuple[str, str] | None:
	if not token:
		return None
	try:
		body_token, signature_token = token.split(".", 1)
		body = base64.urlsafe_b64decode(body_token + "=" * (-len(body_token) % 4))
		signature = base64.urlsafe_b64decode(signature_token + "=" * (-len(signature_token) % 4))
		if not hmac.compare_digest(signature, hmac.new(_secret(), body, hashlib.sha256).digest()):
			raise ValueError
		payload = json.loads(body)
		if payload.get("student") != student or payload.get("policy") != CONTEXT_POLICY_VERSION or not isinstance(payload.get("name"), str):
			raise ValueError
		return str(payload.get("at") or ""), payload["name"]
	except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
		frappe.throw(_("Invalid Student context history cursor."), frappe.PermissionError)


def _event_rows(doctype: str, student: str, limit: int, cursor_key: tuple[str, str] | None = None) -> list[Any]:
	available = _fields(doctype)
	if not _exists(doctype) or "student" not in available:
		return []
	fields = ["name"] + [field for field in ("event_id", "student", "interaction", "outcome_code", "continuity_kind", "next_action", "next_action_assignee", "next_action_due_at", "continuity_reason", "qualification_evidence", "source_doctype", "source_name", "occurred_at", "supersedes", "evidence_references", "from_stage", "to_stage", "transition_kind", "prior_active_stage", "reason", "policy_version") if field in available]
	order_field = "occurred_at" if "occurred_at" in available else "creation"
	filters: dict[str, Any] = {"student": student}
	try:
		if cursor_key and order_field == "occurred_at" and cursor_key[0]:
			selected = ", ".join(f"`{field}`" for field in fields)
			return frappe.db.sql(
				f"select {selected} from `tab{doctype}` where `student` = %s and (`occurred_at` < %s or (`occurred_at` = %s and `name` < %s)) order by `occurred_at` desc, `name` desc limit %s",
				(student, cursor_key[0], cursor_key[0], cursor_key[1], limit),
				as_dict=True,
			)
		return frappe.get_all(doctype, filters=filters, fields=fields, order_by=f"{order_field} desc, name desc", limit_page_length=limit)
	except Exception:
		try:
			return frappe.get_all(doctype, filters=filters, fields=fields, order_by=f"{order_field} desc, name desc", limit_page_length=limit * 2)
		except Exception:
			return []


def _current_events(rows: list[Any]) -> list[Any]:
	superseded = {str(_get(row, "supersedes")) for row in rows if _get(row, "supersedes")}
	return [row for row in rows if str(_get(row, "name", "event_id")) not in superseded]


def _evidence(row: Any, *keys: str, student: str | None = None) -> list[dict[str, str]]:
	value = _get(row, *keys)
	references = redact_evidence(_json(value) or value)
	if not student:
		return references
	visible = []
	for reference in references:
		doctype, name = reference.get("doctype"), reference.get("name")
		if doctype in {"CRM Student Outcome", "CRM Student Lifecycle Event"}:
			# Canonical events are exposed through this Student-scoped adapter;
			# their own DocPerm may intentionally be administrator-only.
			if _linked_student(row) == student:
				visible.append(reference)
			continue
		if not _can_read_record(doctype, name):
			continue
		try:
			linked = frappe.get_doc(doctype, name)
		except Exception:
			continue
		if _linked_student(linked) == student:
			visible.append(reference)
	return visible


def _outcome(row: Any, student: str | None = None) -> dict[str, Any]:
	source_doctype = _get(row, "source_doctype")
	source_name = _get(row, "source_name")
	interaction = _get(row, "interaction")
	interaction_visible = not interaction or _visible_linked_record("CRM Interaction", interaction, student)
	next_action = _get(row, "next_action")
	next_action_visible = not next_action or _visible_linked_record("CRM Action", next_action, student)
	reason_visible = _may_read_audit_reason()
	source_refs = []
	if source_doctype and source_name:
		source_visible = source_doctype in {"CRM Student Outcome", "CRM Student Lifecycle Event"}
		if not source_visible and _visible_linked_record(source_doctype, source_name, student):
			try:
				source_visible = _linked_student(frappe.get_doc(source_doctype, source_name)) == student
			except Exception:
				source_visible = False
		if source_visible:
			source_refs = [{"category": "interaction" if source_doctype == "CRM Interaction" else "document", "doctype": source_doctype, "name": source_name}]
	return {
		"name": _get(row, "name", "event_id"),
		"interaction": interaction if interaction_visible else None,
		"outcome": _get(row, "outcome_code", "outcome"),
		"continuity_kind": _get(row, "continuity_kind"),
		"continuity_reason": _text(_get(row, "continuity_reason")) if reason_visible else None,
		"occurred_at": _iso(_get(row, "occurred_at")),
		"next_action": next_action if next_action_visible else None,
		"next_action_assignee": _get(row, "next_action_assignee") if next_action_visible else None,
		"next_action_due_at": _iso(_get(row, "next_action_due_at")) if next_action_visible else None,
		"qualification_evidence": _evidence(row, "qualification_evidence", "evidence_references", student=student),
		"source_evidence": source_refs,
		"source_evidence_links": source_refs,
		"policy_version": _get(row, "policy_version"),
		"source": "canonical",
	}


def _lifecycle(row: Any, student: str | None = None) -> dict[str, Any]:
	reason_visible = _may_read_audit_reason()
	return {
		"name": _get(row, "name", "event_id"),
		"from_stage": _get(row, "from_stage", "from_status"),
		"to_stage": _get(row, "to_stage", "to_status"),
		"transition_kind": _get(row, "transition_kind"),
		"prior_active_stage": _get(row, "prior_active_stage"),
		"reason": _text(_get(row, "reason")) if reason_visible else None,
		"occurred_at": _iso(_get(row, "occurred_at", "from_date")),
		"evidence": _evidence(row, "evidence_references", "qualification_evidence", student=student),
		"policy_version": _get(row, "policy_version"),
		"source": "canonical",
	}


def _interactions(student: str, limit: int, cursor_key: tuple[str, str] | None = None) -> list[Any]:
	if not _exists("CRM Interaction"):
		return []
	fields = _fields("CRM Interaction")
	try:
		selected_fields = [field for field in ("name", "student", "interaction_datetime", "creation", "interaction_type", "outcome", "summary", "next_follow_up_date", "next_follow_up_action", "reference_doctype", "reference_docname") if field in fields or field == "name"]
		order_field = "interaction_datetime" if "interaction_datetime" in fields else "creation"
		if cursor_key and cursor_key[0]:
			selected = ", ".join(f"`{field}`" for field in selected_fields)
			rows = frappe.db.sql(
				f"select {selected} from `tabCRM Interaction` where `student` = %s and (`{order_field}` < %s or (`{order_field}` = %s and `name` < %s)) order by `{order_field}` desc, `name` desc limit %s",
				(student, cursor_key[0], cursor_key[0], cursor_key[1], limit),
				as_dict=True,
			)
		else:
			rows = frappe.get_all("CRM Interaction", filters={"student": student}, fields=selected_fields, order_by=f"{order_field} desc, name desc", limit_page_length=limit)
		return [row for row in rows if _can_read_record("CRM Interaction", _get(row, "name")) and _linked_student(row) == student and (not cursor_key or (str(_get(row, order_field) or ""), str(_get(row, "name") or "")) < cursor_key)]
	except Exception:
		try:
			rows = frappe.get_all("CRM Interaction", filters={"student": student}, fields=[field for field in ("name", "student", "interaction_datetime", "interaction_type", "outcome", "summary", "next_follow_up_date", "next_follow_up_action", "reference_doctype", "reference_docname") if field in fields], order_by="interaction_datetime desc, name desc", limit_page_length=limit * 2)
			return [row for row in rows if _can_read_record("CRM Interaction", _get(row, "name")) and _linked_student(row) == student and (not cursor_key or (str(_get(row, order_field) or ""), str(_get(row, "name") or "")) < cursor_key)]
		except Exception:
			return []


def _interaction(row: Any) -> dict[str, Any]:
	return {
		"name": _get(row, "name"),
		"interaction_type": _get(row, "interaction_type"),
		"outcome": _get(row, "outcome"),
		"summary": _text(_get(row, "summary")),
		"occurred_at": _iso(_get(row, "interaction_datetime")),
		"next_follow_up_date": _iso(_get(row, "next_follow_up_date")),
		"next_follow_up_action": _text(_get(row, "next_follow_up_action")),
		"source": "compatibility",
	}


def _next_action(student: str, interaction: str | None = None) -> dict[str, Any] | None:
	if not _exists("CRM Action"):
		return None
	try:
		rows = frappe.get_all("CRM Action", filters={"student": student, "state": ["in", ["pending", "accepted", "in-progress", "requires-review", "deferred"]]}, fields=["name", "student", "objective", "action_owner", "due_at", "state", "action_type"], order_by="due_at asc, name asc", limit_page_length=100)
	except Exception:
		return None
	for row in rows:
		if not _can_read_record("CRM Action", _get(row, "name")) or _linked_student(row) != student:
			continue
		status = str(_get(row, "state", default="")).casefold()
		if status in {"completed", "cancelled", "rejected", "superseded"}:
			continue
		due = _get(row, "due_at")
		overdue = False
		if due:
			try:
				now = frappe.utils.now_datetime()
				overdue = due.date() < now.date() if isinstance(due, datetime) else due < now.date()
			except (AttributeError, TypeError):
				overdue = False
		return {"name": _get(row, "name"), "title": _text(_get(row, "objective")), "assigned_to": _get(row, "action_owner"), "due_date": _iso(due), "status": _get(row, "state"), "action_type": _get(row, "action_type"), "linked_interaction": None, "overdue": overdue}
	return None


def _decision_context(student: str) -> dict[str, Any]:
	"""Bounded Phase 6 projection; it is not a lifecycle input."""
	empty = {"pending_decision": None, "active_action": None, "latest_terminal_action": None, "events": []}
	if not _exists("CRM Action"):
		return empty
	try:
		recommendations = frappe.get_all("CRM Action", filters={"student": student, "current_slot": "CURRENT", "state": ["in", ["pending", "requires-review"]]}, fields=["name", "state", "action_type", "objective", "due_at", "decision_revision"], order_by="creation desc", limit_page_length=1)
		actions = frappe.get_all("CRM Action", filters={"student": student}, fields=["name", "recommendation", "action_type", "state", "execution_status", "due_at", "action_owner", "action_revision", "outcome_code", "objective"], order_by="creation desc", limit_page_length=20)
		def project(row):
			return {"name": _get(row, "name"), "recommendation": _get(row, "recommendation"), "action_type": _get(row, "action_type"), "status": _get(row, "execution_status", "state"), "due_at": _iso(_get(row, "due_at")), "assignee_staff": _get(row, "action_owner"), "revision": _get(row, "action_revision", "decision_revision"), "outcome_code": _get(row, "outcome_code"), "objective": _text(_get(row, "objective"))}
		active = next((project(row) for row in actions if _get(row, "state") in {"accepted", "in-progress"}), None)
		terminal = next((project(row) for row in actions if _get(row, "state") in {"completed", "cancelled", "rejected", "superseded"}), None)
		events = []
		if _exists("CRM Student Decision Event"):
			events = frappe.get_all("CRM Student Decision Event", filters={"student": student}, fields=["name", "event_id", "event_kind", "occurred_at"], order_by="occurred_at desc, name desc", limit_page_length=5)
		return {"pending_decision": project(recommendations[0]) if recommendations else None, "active_action": active, "latest_terminal_action": terminal, "events": [{"name": _get(row, "name", "event_id"), "kind": _get(row, "event_kind"), "occurred_at": _iso(_get(row, "occurred_at"))} for row in events]}
	except Exception:
		return empty


def get_student_context(student: str, history_limit: int | str = 20, history_cursor: str | None = None) -> dict[str, Any]:
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	if not enabled("context_read"):
		frappe.throw(_("Student context is disabled by rollout policy."), frappe.PermissionError)
	limit = _limit(history_limit)
	cursor_key = _verify_cursor(history_cursor, student)
	doc = frappe.get_doc("CRM Student", student)
	if not doc.has_permission("read"):
		frappe.throw(_("You do not have permission to view this Student."), frappe.PermissionError)
	try:
		lifecycle_context = get_lifecycle_context(student)
	except Exception:
		lifecycle_context = {
			"current_stage": doc.get("lifecycle_stage") or "Lead",
			"revision": int(doc.get("lifecycle_revision") or 0),
			"allowed_targets": [],
			"capabilities": {},
		}
	interactions = _interactions(student, limit + 1, cursor_key)
	outcome_rows = _current_events(_event_rows("CRM Student Outcome", student, limit + 1, cursor_key))
	lifecycle_rows = _current_events(_event_rows("CRM Student Lifecycle Event", student, limit + 1, cursor_key))
	canonical_lifecycle_present = bool(lifecycle_rows)
	legacy = legacy_read_enabled()
	if not lifecycle_rows and legacy and _exists("CRM Enrollment Transition"):
		try:
			if cursor_key and cursor_key[0]:
				lifecycle_rows = frappe.db.sql(
					"select `name`, `from_status`, `to_status`, `from_date`, `to_date` from `tabCRM Enrollment Transition` where `student` = %s and (`from_date` < %s or (`from_date` = %s and `name` < %s)) order by `from_date` desc, `name` desc limit %s",
					(student, cursor_key[0], cursor_key[0], cursor_key[1], limit + 1),
					as_dict=True,
				)
			else:
				lifecycle_rows = frappe.get_all("CRM Enrollment Transition", filters={"student": student}, fields=["name", "from_status", "to_status", "from_date", "to_date"], order_by="from_date desc, name desc", limit_page_length=limit + 1)
			lifecycle_rows = [row for row in lifecycle_rows if _can_read_record("CRM Enrollment Transition", _get(row, "name"))]
		except Exception:
			try:
				lifecycle_rows = frappe.get_all("CRM Enrollment Transition", filters={"student": student}, fields=["name", "from_status", "to_status", "from_date", "to_date"], order_by="from_date desc, name desc", limit_page_length=(limit + 1) * 2)
				lifecycle_rows = [row for row in lifecycle_rows if _can_read_record("CRM Enrollment Transition", _get(row, "name")) and (not cursor_key or (str(_get(row, "from_date") or ""), str(_get(row, "name") or "")) < cursor_key)]
			except Exception:
				lifecycle_rows = []
	latest_interaction_name = _get(outcome_rows[0], "interaction") if outcome_rows else None
	latest_interaction = next((_interaction(row) for row in interactions if _get(row, "name") == latest_interaction_name), None)
	if latest_interaction is None and interactions and (outcome_rows or legacy):
		latest_interaction = _interaction(interactions[0])
	outcomes = [_outcome(row, student) for row in outcome_rows[:limit]]
	if not outcomes and legacy:
		outcomes = [_interaction(row) for row in interactions[:limit]]
	history = sorted([*[_lifecycle(row, student) for row in lifecycle_rows[:limit]], *outcomes], key=lambda item: (str(item.get("occurred_at") or ""), str(item.get("name") or "")), reverse=True)
	if cursor_key:
		history = [item for item in history if (str(item.get("occurred_at") or ""), str(item.get("name") or "")) < cursor_key]
	page = history[:limit]
	conversion_read_enabled = enabled("conversion_read")
	conversion_write_enabled = enabled("conversion_write")
	conversion_rows = conversion_rows_for_student(student, limit=1) if conversion_read_enabled else []
	conversion = None
	if conversion_read_enabled and conversion_rows:
		row = conversion_rows[0]
		conversion = {
			"status": "converted",
			"contact": _get(row, "contact"),
			"converted_at": _iso(_get(row, "converted_at")),
			"actor": _get(row, "actor"),
			"conversion": _get(row, "name"),
		}
	actor = getattr(getattr(frappe, "session", None), "user", None)
	try:
		conversion_capabilities = capabilities_for_roles(frappe.get_roles(actor), administrator=actor == "Administrator")
	except Exception:
		conversion_capabilities = set()
	conversion_can_convert = bool(
		conversion_read_enabled
		and conversion_write_enabled
		and lifecycle_context.get("current_stage") == "Enrolled"
		and (actor in {"Administrator"} or "conversion.execute" in conversion_capabilities)
	)
	if not conversion_read_enabled:
		conversion = {
			"status": "unavailable",
			"can_convert": False,
			"read_enabled": False,
			"write_enabled": conversion_write_enabled,
			"lifecycle_revision": int(doc.get("lifecycle_revision") or 0),
		}
	elif conversion is None:
		conversion = {
			"status": "eligible" if conversion_can_convert else "not_eligible",
			"can_convert": conversion_can_convert,
			"read_enabled": True,
			"write_enabled": conversion_write_enabled,
			"lifecycle_revision": int(doc.get("lifecycle_revision") or 0),
		}
	else:
		conversion["can_convert"] = False
		conversion["read_enabled"] = True
		conversion["write_enabled"] = conversion_write_enabled
	return {
		"student": {"name": doc.name, "student_name": doc.get("student_name"), "owner_staff": doc.get("owner_staff") or doc.get("assigned_to"), "assigned_to": doc.get("assigned_to"), "owning_team": doc.get("owning_team"), "owning_pool": doc.get("owning_pool")},
		"engagement_revision": int(doc.get("engagement_revision") or 0),
		"lifecycle": {**lifecycle_context, "stage": lifecycle_context.get("current_stage") or doc.get("lifecycle_stage"), "enrollment_status": doc.get("enrollment_status"), "lost": next((item for item in history if item.get("to_stage") == "Lost"), None), "reopen": next((item for item in history if item.get("transition_kind") == "reopen"), None)},
		"latest_interaction": latest_interaction,
		"latest_outcome": _outcome(outcome_rows[0], student) if outcome_rows else None,
		"next_action": _next_action(student, latest_interaction_name),
		"decision": _decision_context(student),
		"conversion": conversion,
		# Attribution is evidence-only and scoped by the Student permission
		# check above.  A malformed/legacy row must never make the core context
		# unavailable, so an empty bounded projection is safer than surfacing a
		# partial Contact fallback.
		"attribution": _attribution_context(student),
		"qualification_evidence": _evidence(outcome_rows[0], "qualification_evidence", student=student) if outcome_rows else [],
		"history": page,
		"next_cursor": _cursor(student, page[-1]) if len(history) > limit and page else None,
		"policy_version": CONTEXT_POLICY_VERSION,
		"legacy_read": bool(legacy and (not outcome_rows or not canonical_lifecycle_present)),
	}


def _attribution_context(student: str) -> dict[str, Any]:
	try:
		projection = get_student_attribution(student)
		return {
			"first_touch": projection["firstTouch"],
			"last_touch": projection["lastTouch"],
			"equal_credit": projection["multiTouch"],
			"timeline": projection["touchpoints"][:MAX_HISTORY_LIMIT],
		}
	except Exception:
		return {"first_touch": None, "last_touch": None, "equal_credit": {}, "timeline": []}
