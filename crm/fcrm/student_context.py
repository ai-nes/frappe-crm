"""Permission-scoped Student engagement context read service.

This module is a read model only.  Outcome/lifecycle command services remain
the sole event writers; raw Interaction rows are only used to surface the
latest touchpoint alongside an existing CRM Student Outcome, never as a
substitute event source.
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
from crm.fcrm.student_feature_flags import enabled
from crm.fcrm.student_lifecycle import get_lifecycle_context
from crm.fcrm.attribution import get_student_attribution
from crm.fcrm.student_contact_conversion import conversion_rows_for_student

CONTEXT_POLICY_VERSION = "student-context"
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
	next_action_visible = not next_action or _visible_linked_record("CRM Action Item", next_action, student)
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
	if not _exists("CRM Action Item"):
		return None
	try:
		rows = frappe.get_all("CRM Action Item", filters={"student": student, "state": ["in", ["pending", "accepted", "in-progress", "requires-review", "deferred"]]}, fields=["name", "student", "action", "objective", "action_owner", "due_at", "state", "action_type"], order_by="due_at asc, name asc", limit_page_length=100)
	except Exception:
		return None
	for row in rows:
		if not _can_read_record("CRM Action Item", _get(row, "name")) or _linked_student(row) != student:
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
		return {"name": _get(row, "name"), "title": _text(_get(row, "objective")), "assigned_to": _get(row, "action_owner"), "due_date": _iso(due), "status": _get(row, "state"), "action": _get(row, "action"), "action_type": _get(row, "action_type"), "linked_interaction": None, "overdue": overdue}
	return None


def _decision_context(student: str) -> dict[str, Any]:
	"""Bounded Phase 6 projection; it is not a lifecycle input."""
	empty = {"pending_decision": None, "active_action": None, "latest_terminal_action": None, "events": []}
	if not _exists("CRM Action Item"):
		return empty
	try:
		recommendations = frappe.get_all("CRM Action Item", filters={"student": student, "current_slot": "CURRENT", "state": ["in", ["pending", "requires-review"]]}, fields=["name", "state", "action", "action_type", "objective", "due_at", "decision_revision"], order_by="creation desc", limit_page_length=1)
		actions = frappe.get_all("CRM Action Item", filters={"student": student}, fields=["name", "recommendation", "action", "action_type", "state", "execution_status", "due_at", "action_owner", "action_revision", "outcome_code", "objective"], order_by="creation desc", limit_page_length=20)
		def project(row):
			return {"name": _get(row, "name"), "recommendation": _get(row, "recommendation"), "action": _get(row, "action"), "action_type": _get(row, "action_type"), "status": _get(row, "execution_status", "state"), "due_at": _iso(_get(row, "due_at")), "assignee_staff": _get(row, "action_owner"), "revision": _get(row, "action_revision", "decision_revision"), "outcome_code": _get(row, "outcome_code"), "objective": _text(_get(row, "objective"))}
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
	latest_interaction_name = _get(outcome_rows[0], "interaction") if outcome_rows else None
	latest_interaction = next((_interaction(row) for row in interactions if _get(row, "name") == latest_interaction_name), None)
	if latest_interaction is None and interactions and outcome_rows:
		latest_interaction = _interaction(interactions[0])
	outcomes = [_outcome(row, student) for row in outcome_rows[:limit]]
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
	attribution_projection = _attribution_projection(student)
	assessment_context = _assessment_context(student)
	parent_context = _parent_context(student)
	privacy_context = _privacy_context(student, doc)
	geography_context = _geography_context(student)
	return {
		"student": {
			"name": doc.name,
			"student_name": doc.get("student_name"),
			"high_school": doc.get("high_school"),
			"province": doc.get("province"),
			"ward": doc.get("ward"),
			"current_grade": doc.get("current_grade"),
			"study_stage": doc.get("study_stage"),
			"assessment_status": doc.get("assessment_status"),
			"assessment_revision": doc.get("assessment_revision"),
			"interest_level": doc.get("interest_level"),
			"fit_level": doc.get("fit_level"),
			"primary_barrier": doc.get("primary_barrier"),
			"privacy_status": doc.get("privacy_status"),
			"owner_staff": doc.get("owner_staff") or doc.get("assigned_to"),
			"assigned_to": doc.get("assigned_to"),
			"owning_team": doc.get("owning_team"),
			"owning_pool": doc.get("owning_pool"),
		},
		"engagement_revision": int(doc.get("engagement_revision") or 0),
		"lifecycle": {**lifecycle_context, "stage": lifecycle_context.get("current_stage") or doc.get("lifecycle_stage"), "enrollment_status": doc.get("enrollment_status"), "lost": next((item for item in history if item.get("to_stage") == "Lost"), None), "reopen": next((item for item in history if item.get("transition_kind") == "reopen"), None)},
		"latest_interaction": latest_interaction,
		"latest_outcome": _outcome(outcome_rows[0], student) if outcome_rows else None,
		"next_action": _next_action(student, latest_interaction_name),
		"decision": _decision_context(student),
		"conversion": conversion,
		# Raw attribution evidence (campaign/event IDs and touchpoint metadata) is
		# intentionally not part of the Student Detail DTO.  Admissions receives
		# only the redacted ``admissions_context`` projection below.
		"admissions_context": _admissions_context(student, doc, attribution_projection),
		"assessment": assessment_context,
		"parent_context": parent_context,
		"privacy": privacy_context,
		"geography": geography_context,
		"qualification_evidence": _evidence(outcome_rows[0], "qualification_evidence", student=student) if outcome_rows else [],
		"history": page,
		"next_cursor": _cursor(student, page[-1]) if len(history) > limit and page else None,
		"policy_version": CONTEXT_POLICY_VERSION,
	}


def _assessment_context(student: str) -> dict[str, Any]:
	"""Return the canonical assessment read model without making context brittle."""
	try:
		from crm.fcrm.student_assessment import get_student_assessment_context

		return get_student_assessment_context(student)
	except Exception:
		return {"current": None, "pending": None, "history": [], "policy_version": None}


def _parent_context(student: str) -> list[dict[str, Any]]:
	if not _exists("CRM Parent Contact Authority"):
		return []
	try:
		rows = frappe.get_all(
			"CRM Parent Contact Authority",
			filters={"student": student},
			fields=[
				"name", "contact", "relationship_type", "relationship_verified",
				"decision_role", "decision_influence", "concerns", "allowed_channels",
				"lawful_basis", "effective_at", "expires_at", "revoked_at",
			],
			order_by="effective_at desc",
			limit_page_length=20,
		)
		output = []
		now = frappe.utils.now_datetime()
		for row in rows:
			if not _can_read_record("CRM Parent Contact Authority", row.get("name")):
				continue
			if row.get("contact") and not _can_read_record("CRM Student", row.get("contact")):
				continue
			if row.get("revoked_at") or (row.get("expires_at") and row.get("expires_at") <= now) or (row.get("effective_at") and row.get("effective_at") > now):
				continue
			output.append(
				{
					"name": row.get("name"),
					"contact": row.get("contact"),
					"relationship_type": row.get("relationship_type"),
					"relationship_verified": bool(row.get("relationship_verified")),
					"decision_role": row.get("decision_role") or "Unknown",
					"decision_influence": row.get("decision_influence") or "Unknown",
					"concerns": _text(row.get("concerns"), 1000),
					"allowed_channels": _json(row.get("allowed_channels")) or [],
					"lawful_basis": row.get("lawful_basis"),
					"effective_at": _iso(row.get("effective_at")),
					"expires_at": _iso(row.get("expires_at")),
					"revoked_at": _iso(row.get("revoked_at")),
				}
			)
		return output
	except Exception:
		return []


def _privacy_context(student: str, doc: Any) -> dict[str, Any]:
	requests = []
	consent_at = None
	retention_until = None
	if _exists("CRM Contact Consent Event"):
		try:
			consent_rows = frappe.get_all(
				"CRM Contact Consent Event",
				filters={"student": student},
				fields=["name", "occurred_at", "granted_at"],
				order_by="occurred_at desc, creation desc",
				limit_page_length=1,
			)
			if consent_rows and _can_read_record("CRM Contact Consent Event", consent_rows[0].get("name")):
				consent = consent_rows[0]
				consent_at = consent.get("granted_at") or consent.get("occurred_at")
				retention_days = frappe.conf.get("crm_student_privacy_retention_days")
				try:
					retention_days = int(retention_days) if retention_days not in (None, "") else None
				except (TypeError, ValueError):
					retention_days = None
				if retention_days and retention_days > 0 and consent.get("occurred_at"):
					retention_until = frappe.utils.add_days(consent.get("occurred_at"), retention_days)
		except Exception:
			consent_at = None
			retention_until = None
	if _exists("CRM Student Privacy Request"):
		try:
			rows = frappe.get_all(
				"CRM Student Privacy Request",
				filters={"student": student},
				fields=["name", "request_type", "status", "requested_at", "requested_by", "resolved_at", "resolved_by", "resolution", "evidence_reference"],
				order_by="requested_at desc",
				limit_page_length=20,
			)
			for row in rows:
				if _can_read_record("CRM Student Privacy Request", row.get("name")):
					requests.append(
						{
							"name": row.get("name"),
							"request_type": row.get("request_type"),
							"status": row.get("status"),
							"requested_at": _iso(row.get("requested_at")),
							"requested_by": row.get("requested_by"),
							"resolved_at": _iso(row.get("resolved_at")),
							"resolved_by": row.get("resolved_by"),
							"resolution": _text(row.get("resolution"), 1000),
							"evidence_reference": row.get("evidence_reference"),
						}
					)
		except Exception:
			requests = []
	return {
		"status": doc.get("privacy_status") or "unknown",
		"consent_at": _iso(consent_at),
		"retention_until": _iso(retention_until),
		"requests": requests,
	}


def _geography_context(student: str) -> dict[str, Any]:
	"""Expose dated geography snapshots without leaking unrelated Student rows."""
	if not _exists("CRM Student Geography Snapshot"):
		return {"current": None, "history": []}
	try:
		rows = frappe.get_all(
			"CRM Student Geography Snapshot",
			filters={"student": student},
			fields=["name", "captured_at", "province", "ward", "high_school", "source", "change_reason"],
			order_by="captured_at desc, name desc",
			limit_page_length=20,
		)
		history = []
		for row in rows:
			if not _can_read_record("CRM Student Geography Snapshot", row.get("name")):
				continue
			history.append(
				{
					"name": row.get("name"),
					"captured_at": _iso(row.get("captured_at")),
					"province": row.get("province"),
					"ward": row.get("ward"),
					"high_school": row.get("high_school"),
					"source": row.get("source"),
					"change_reason": _text(row.get("change_reason"), 500),
				}
			)
		return {"current": history[0] if history else None, "history": history}
	except Exception:
		return {"current": None, "history": []}


def _attribution_projection(student: str) -> dict[str, Any]:
	try:
		return get_student_attribution(student)
	except Exception:
		return {"firstTouch": None, "lastTouch": None, "multiTouch": {}, "touchpoints": []}


def _attribution_context(projection: dict[str, Any]) -> dict[str, Any]:
	return {
		"first_touch": projection["firstTouch"],
		"last_touch": projection["lastTouch"],
		"equal_credit": projection["multiTouch"],
		"timeline": projection["touchpoints"][:MAX_HISTORY_LIMIT],
	}


def _admissions_context(student: str, doc: Any, attribution: dict[str, Any]) -> dict[str, Any]:
	"""Display-only admissions projection for the Student Detail workspace."""
	try:
		from crm.fcrm.student_admissions import ACTION_CAPABILITIES
		actor = getattr(getattr(frappe, "session", None), "user", None)
		roles = frappe.get_roles(actor)
		capabilities = capabilities_for_roles(roles, administrator=actor == "Administrator")
		actions = [
			name
			for name, required in ACTION_CAPABILITIES.items()
			if actor == "Administrator" or "System Manager" in roles or required in capabilities or "admissions.oversee" in capabilities
		]
		document_visibility = actor == "Administrator" or "System Manager" in roles or "admissions.oversee" in capabilities
	except Exception:
		actions = []
		document_visibility = False
	touchpoints = [row for row in attribution.get("touchpoints", []) if not row.get("superseded")]
	campaign_touchpoints = [row for row in touchpoints if row.get("campaign")]
	event_touchpoints = [row for row in touchpoints if row.get("event")]
	latest_campaign = campaign_touchpoints[-1] if campaign_touchpoints else None
	latest_event = event_touchpoints[-1] if event_touchpoints else None

	activity = []
	for index, row in enumerate(touchpoints):
		occurred_at = _iso(row.get("touched_at"))
		if not occurred_at:
			continue
		if row.get("event") and row.get("status"):
			activity.append(
				{
					"key": f"event-{index}",
					"occurred_at": occurred_at,
					"summary": _event_activity_summary(row.get("status"), row.get("event")),
				}
			)
		elif _is_invitation_source(row.get("source")):
			activity.append(
				{
					"key": f"campaign-{index}",
					"occurred_at": occurred_at,
					"summary": _("Invited to {0}").format(row.get("campaign") or _("admissions event")),
				}
			)

	scholarship = _scholarship_interest(student)
	next_action = _next_action(student)
	input_revision = int(doc.get("score_input_revision") or 0)
	applied_revision = int(doc.get("applied_score_input_revision") or 0)
	return {
		"current_grade": doc.get("current_grade"),
		"study_stage": doc.get("study_stage"),
		"assessment_status": doc.get("assessment_status"),
		"interest": doc.get("interest_level"),
		"fit": doc.get("fit_level"),
		"primary_barrier": doc.get("primary_barrier"),
		"campaign": _demo_campaign(latest_campaign),
		"event": _demo_event(latest_event),
		"scholarship": scholarship,
		"next_action": {
			"summary": next_action.get("title"),
			"due_at": next_action.get("due_date"),
		}
		if next_action
		else None,
		"activity": [row for row in activity if row.get("summary")],
		"capabilities": {"actions": actions, "document_visibility": document_visibility},
		"score": {
			"latest": doc.get("latest_score"),
			"input_revision": input_revision,
			"applied_input_revision": applied_revision,
			"state": "unknown" if doc.get("latest_score") in (None, "") else ("current" if input_revision == applied_revision else "pending"),
		},
	}


# Kept for local precursor tests while the production DTO migrates to its
# admissions_context name. No API response exposes this compatibility symbol.
def _demo_context(student: str, attribution: dict[str, Any]) -> dict[str, Any]:
	return _admissions_context(student, {}, attribution)


def _demo_campaign(row: dict[str, Any] | None) -> dict[str, Any] | None:
	if not row:
		return None
	return {
		"label": _text(row.get("campaign")),
		"source": _text(row.get("source")),
		"occurred_at": _iso(row.get("touched_at")),
	}


def _demo_event(row: dict[str, Any] | None) -> dict[str, Any] | None:
	if not row:
		return None
	return {
		"label": _text(row.get("event")),
		"status": _text(row.get("status")),
		"occurred_at": _iso(row.get("touched_at")),
	}


def _is_invitation_source(source: Any) -> bool:
	return "invite" in str(source or "").casefold() or "mời" in str(source or "").casefold()


def _event_activity_summary(status: Any, event: Any) -> str:
	label = _text(event) or _("admissions event")
	status_key = str(status or "").casefold()
	if "check" in status_key:
		return _("Checked in at {0}").format(label)
	if "register" in status_key:
		return _("Registered for {0}").format(label)
	if "invite" in status_key:
		return _("Invited to {0}").format(label)
	return _("Event update: {0}").format(label)


def _scholarship_interest(student: str) -> dict[str, Any] | None:
	if not _exists("CRM Intent"):
		return None
	try:
		rows = frappe.get_all(
			"CRM Intent",
			filters={"student": student, "intent_type": "Scholarship"},
			fields=["name", "student", "intent_type", "importance", "confidence", "notes", "modified", "creation"],
			order_by="modified desc, creation desc, name desc",
			limit_page_length=20,
		)
	except Exception:
		return None
	for row in rows:
		if _get(row, "student") != student or not _can_read_record("CRM Intent", _get(row, "name")):
			continue
		return {
			"label": _text(_get(row, "intent_type")),
			"importance": _text(_get(row, "importance")),
			"confidence": _get(row, "confidence"),
			"notes": _text(_get(row, "notes")),
		}
	return None
