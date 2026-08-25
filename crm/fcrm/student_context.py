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
from crm.fcrm.student_feature_flags import enabled, legacy_read_enabled
from crm.fcrm.student_lifecycle import get_lifecycle_context

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


def _verify_cursor(token: str | None, student: str) -> None:
	if not token:
		return
	try:
		body_token, signature_token = token.split(".", 1)
		body = base64.urlsafe_b64decode(body_token + "=" * (-len(body_token) % 4))
		signature = base64.urlsafe_b64decode(signature_token + "=" * (-len(signature_token) % 4))
		if not hmac.compare_digest(signature, hmac.new(_secret(), body, hashlib.sha256).digest()):
			raise ValueError
		payload = json.loads(body)
		if payload.get("student") != student or payload.get("policy") != CONTEXT_POLICY_VERSION or not isinstance(payload.get("name"), str):
			raise ValueError
	except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
		frappe.throw(_("Invalid Student context history cursor."), frappe.PermissionError)


def _event_rows(doctype: str, student: str, limit: int) -> list[Any]:
	available = _fields(doctype)
	if not _exists(doctype) or "student" not in available:
		return []
	fields = ["name"] + [field for field in ("event_id", "student", "interaction", "outcome_code", "continuity_kind", "next_action", "next_action_assignee", "next_action_due_at", "continuity_reason", "qualification_evidence", "source_doctype", "source_name", "occurred_at", "supersedes", "evidence_references", "from_stage", "to_stage", "transition_kind", "prior_active_stage", "reason", "policy_version") if field in available]
	order_field = "occurred_at" if "occurred_at" in available else "creation"
	try:
		return frappe.get_all(doctype, filters={"student": student}, fields=fields, order_by=f"{order_field} desc, name desc", limit_page_length=limit)
	except Exception:
		return []


def _current_events(rows: list[Any]) -> list[Any]:
	superseded = {str(_get(row, "supersedes")) for row in rows if _get(row, "supersedes")}
	return [row for row in rows if str(_get(row, "name", "event_id")) not in superseded]


def _evidence(row: Any, *keys: str) -> list[dict[str, str]]:
	value = _get(row, *keys)
	return redact_evidence(_json(value) or value)


def _outcome(row: Any) -> dict[str, Any]:
	source_doctype = _get(row, "source_doctype")
	source_name = _get(row, "source_name")
	source_refs = (
		[{"category": "interaction" if source_doctype == "CRM Interaction" else "document", "doctype": source_doctype, "name": source_name}]
		if source_doctype and source_name
		else []
	)
	return {
		"name": _get(row, "name", "event_id"),
		"interaction": _get(row, "interaction"),
		"outcome": _get(row, "outcome_code", "outcome"),
		"continuity_kind": _get(row, "continuity_kind"),
		"continuity_reason": _text(_get(row, "continuity_reason")),
		"occurred_at": _iso(_get(row, "occurred_at")),
		"next_action": _get(row, "next_action"),
		"next_action_assignee": _get(row, "next_action_assignee"),
		"next_action_due_at": _iso(_get(row, "next_action_due_at")),
		"qualification_evidence": _evidence(row, "qualification_evidence", "evidence_references"),
		"source_evidence": source_refs,
		"source_evidence_links": source_refs,
		"policy_version": _get(row, "policy_version"),
		"source": "canonical",
	}


def _lifecycle(row: Any) -> dict[str, Any]:
	return {
		"name": _get(row, "name", "event_id"),
		"from_stage": _get(row, "from_stage", "from_status"),
		"to_stage": _get(row, "to_stage", "to_status"),
		"transition_kind": _get(row, "transition_kind"),
		"prior_active_stage": _get(row, "prior_active_stage"),
		"reason": _text(_get(row, "reason")),
		"occurred_at": _iso(_get(row, "occurred_at", "from_date")),
		"evidence": _evidence(row, "evidence_references", "qualification_evidence"),
		"policy_version": _get(row, "policy_version"),
		"source": "canonical",
	}


def _interactions(student: str, limit: int) -> list[Any]:
	if not _exists("CRM Interaction"):
		return []
	fields = _fields("CRM Interaction")
	try:
		return frappe.get_all("CRM Interaction", filters={"student": student}, fields=[field for field in ("name", "interaction_datetime", "interaction_type", "outcome", "summary", "next_follow_up_date", "next_follow_up_action", "reference_doctype", "reference_docname") if field in fields], order_by="interaction_datetime desc, name desc", limit_page_length=limit)
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
	if not _exists("Task"):
		return None
	fields = _fields("Task")
	if "student" in fields:
		filters = {"student": student}
	elif {"reference_doctype", "reference_docname"} <= fields:
		filters = {"reference_doctype": "CRM Student", "reference_docname": student}
	else:
		return None
	try:
		rows = frappe.get_all("Task", filters=filters, fields=[field for field in ("name", "title", "assigned_to", "due_date", "status", "linked_interaction") if field in fields], order_by="due_date asc, name asc", limit_page_length=100)
	except Exception:
		return None
	for row in rows:
		status = str(_get(row, "status", default="")).casefold()
		if status in DONE_TASK_STATUSES or (interaction and _get(row, "linked_interaction") not in (None, "", interaction)):
			continue
		due = _get(row, "due_date")
		overdue = False
		if due:
			try:
				now = frappe.utils.now_datetime()
				overdue = due.date() < now.date() if isinstance(due, datetime) else due < now.date()
			except (AttributeError, TypeError):
				overdue = False
		return {"name": _get(row, "name"), "title": _text(_get(row, "title")), "assigned_to": _get(row, "assigned_to"), "due_date": _iso(due), "status": _get(row, "status"), "linked_interaction": _get(row, "linked_interaction"), "overdue": overdue}
	return None


def get_student_context(student: str, history_limit: int | str = 20, history_cursor: str | None = None) -> dict[str, Any]:
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	if not enabled("context_read"):
		frappe.throw(_("Student context is disabled by rollout policy."), frappe.PermissionError)
	limit = _limit(history_limit)
	_verify_cursor(history_cursor, student)
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
	interactions = _interactions(student, limit + 1)
	outcome_rows = _current_events(_event_rows("CRM Student Outcome", student, limit + 1))
	lifecycle_rows = _current_events(_event_rows("CRM Student Lifecycle Event", student, limit + 1))
	legacy = legacy_read_enabled()
	if not lifecycle_rows and legacy and _exists("CRM Enrollment Transition"):
		try:
			lifecycle_rows = frappe.get_all("CRM Enrollment Transition", filters={"student": student}, fields=["name", "from_status", "to_status", "from_date", "to_date"], order_by="from_date desc, name desc", limit_page_length=limit + 1)
		except Exception:
			lifecycle_rows = []
	latest_interaction_name = _get(outcome_rows[0], "interaction") if outcome_rows else None
	latest_interaction = next((_interaction(row) for row in interactions if _get(row, "name") == latest_interaction_name), None)
	if latest_interaction is None and interactions and (outcome_rows or legacy):
		latest_interaction = _interaction(interactions[0])
	outcomes = [_outcome(row) for row in outcome_rows[:limit]]
	if not outcomes and legacy:
		outcomes = [_interaction(row) for row in interactions[:limit]]
	history = sorted([*[_lifecycle(row) for row in lifecycle_rows[:limit]], *outcomes], key=lambda item: (str(item.get("occurred_at") or ""), str(item.get("name") or "")), reverse=True)
	page = history[:limit]
	return {
		"student": {"name": doc.name, "student_name": doc.get("student_name"), "owner_staff": doc.get("owner_staff") or doc.get("assigned_to"), "assigned_to": doc.get("assigned_to"), "owning_team": doc.get("owning_team"), "owning_pool": doc.get("owning_pool")},
		"lifecycle": {**lifecycle_context, "stage": lifecycle_context.get("current_stage") or doc.get("lifecycle_stage"), "enrollment_status": doc.get("enrollment_status"), "lost": next((item for item in history if item.get("to_stage") == "Lost"), None), "reopen": next((item for item in history if item.get("transition_kind") == "reopen"), None)},
		"latest_interaction": latest_interaction,
		"latest_outcome": _outcome(outcome_rows[0]) if outcome_rows else None,
		"next_action": _next_action(student, latest_interaction_name),
		"qualification_evidence": _evidence(outcome_rows[0], "qualification_evidence") if outcome_rows else [],
		"history": page,
		"next_cursor": _cursor(student, page[-1]) if len(history) > limit and page else None,
		"policy_version": CONTEXT_POLICY_VERSION,
		"legacy_read": not bool(outcome_rows or (lifecycle_rows and not legacy)),
	}
