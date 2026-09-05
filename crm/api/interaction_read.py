"""Authorized, interaction-centred read contracts for Sales surfaces.

The API deliberately keeps provider payloads and raw evidence out of the feed.
Every public entry point resolves its target through the canonical Interaction
permission hook before reading child records, then verifies the joined rows
again before returning them.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import timezone
from typing import Any

import frappe
from frappe import _
from frappe.utils import get_datetime

from crm.fcrm.permissions import get_interaction_permission_query_conditions

CONTRACT_VERSION = "interaction.read:v1"
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
_EVIDENCE_CONTENT_ROLES = frozenset(
	{"Administrator", "System Manager", "CRM Manager", "Admissions Director", "Admissions Operations"}
)


def _iso(value: Any) -> str | None:
	if not value:
		return None
	return get_datetime(value).replace(tzinfo=timezone.utc).isoformat()


def _page_size(limit: int | str | None) -> int:
	try:
		return min(max(int(limit or DEFAULT_PAGE_SIZE), 1), MAX_PAGE_SIZE)
	except (TypeError, ValueError):
		frappe.throw(_("Invalid page size."), frappe.ValidationError)


def _as_bool(value: bool | str) -> bool:
	if isinstance(value, bool):
		return value
	if str(value).lower() in {"1", "true"}:
		return True
	if str(value).lower() in {"0", "false", ""}:
		return False
	frappe.throw(_("Invalid boolean value."), frappe.ValidationError)


def _encode_cursor(row: dict[str, Any]) -> str:
	body = {"at": _iso(row.get("interaction_datetime")), "name": row["name"]}
	return base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[str, str] | None:
	if not cursor:
		return None
	try:
		decoded = base64.urlsafe_b64decode(str(cursor) + "=" * (-len(str(cursor)) % 4))
		body = json.loads(decoded.decode())
		at, name = str(body["at"]), str(body["name"])
		if not at or not name:
			raise ValueError
		return at, name
	except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
		frappe.throw(_("Invalid interaction cursor."), frappe.ValidationError)


def _require_target(*, student: str | None, contact: str | None) -> tuple[str, str]:
	student, contact = str(student or "").strip(), str(contact or "").strip()
	if bool(student) == bool(contact):
		frappe.throw(_("Provide exactly one Student or Contact."), frappe.ValidationError)
	target_type, target = ("CRM Student", student) if student else ("CRM Contact", contact)
	if frappe.session.user == "Guest" or not frappe.has_permission(target_type, "read", target):
		frappe.throw(_("You are not allowed to view these interactions."), frappe.PermissionError)
	return target_type, target


def _require_interaction(name: str) -> Any:
	name = str(name or "").strip()
	if not name or not frappe.db.exists("CRM Interaction", name):
		frappe.throw(_("Interaction not found."), frappe.DoesNotExistError)
	if not frappe.has_permission("CRM Interaction", "read", name):
		frappe.throw(_("You are not allowed to view this interaction."), frappe.PermissionError)
	return frappe.get_doc("CRM Interaction", name)


def _safe_analysis(interaction: str) -> dict[str, Any] | None:
	runs = frappe.get_all(
		"CRM Interaction Analysis Run",
		filters={"interaction": interaction},
		pluck="name",
	)
	if not runs:
		return None
	rows = frappe.get_all(
		"CRM Interaction Analysis Result",
		filters={"analysis_run": ["in", runs]},
		fields=[
			"name",
			"analysis_run",
			"state",
			"source_revision",
			"source_digest",
			"result_digest",
			"policy_revision",
			"model_revision",
			"intent",
			"terminal_reason",
		],
		order_by="creation desc",
	)
	return dict(rows[0]) if rows else None


def _summary(row: dict[str, Any]) -> dict[str, Any]:
	return {
		"id": row["name"],
		"occurred_at": _iso(row.get("interaction_datetime")),
		"interaction_type": row.get("interaction_type"),
		"channel": row.get("channel") or None,
		"direction": row.get("direction") or None,
		"outcome": row.get("outcome") or None,
		"summary": row.get("summary") or "",
		"episode_state": row.get("episode_state") or None,
		"source_revision": int(row.get("source_revision") or 0),
		"has_evidence": bool(row.get("evidence")),
	}


@frappe.whitelist()
def list_interactions(
	student: str | None = None,
	contact: str | None = None,
	channel: str | None = None,
	direction: str | None = None,
	status: str | None = None,
	cursor: str | None = None,
	limit: int | str | None = None,
) -> dict[str, Any]:
	"""Return a stable, target-scoped Interaction feed without evidence."""
	target_type, target = _require_target(student=student, contact=contact)
	target_field = "student" if target_type == "CRM Student" else "crm_contact"
	conditions = [f"`{target_field}` = %(target)s"]
	values: dict[str, Any] = {"target": target}
	permission_condition = get_interaction_permission_query_conditions(
		user=frappe.session.user, doctype="CRM Interaction"
	)
	if permission_condition == "1=0":
		return {"contract_version": CONTRACT_VERSION, "items": [], "next_cursor": None}
	if permission_condition:
		conditions.append(f"({permission_condition})")
	for field, value in (("channel", channel), ("direction", direction), ("episode_state", status)):
		if value:
			conditions.append(f"`{field}` = %({field})s")
			values[field] = str(value)
	marker = _decode_cursor(cursor)
	if marker:
		marker_at, marker_name = marker
	page_size = _page_size(limit)
	if marker:
		conditions.append(
			"(interaction_datetime < %(cursor_at)s OR (interaction_datetime = %(cursor_at)s AND name < %(cursor_name)s))"
		)
		values.update({"cursor_at": marker_at, "cursor_name": marker_name})
	values["page_limit"] = page_size + 1
	rows = frappe.db.sql(
		"SELECT name, student, crm_contact, interaction_datetime, interaction_type, channel, direction, outcome, summary, episode_state, source_revision, evidence "
		"FROM `tabCRM Interaction` WHERE "
		+ " AND ".join(conditions)
		+ " ORDER BY interaction_datetime DESC, name DESC LIMIT %(page_limit)s",
		values,
		as_dict=True,
	)
	page = rows[:page_size]
	# The target filter is necessary but not sufficient after joins/cursors.
	for row in page:
		if row.get("student" if target_type == "CRM Student" else "crm_contact") != target:
			frappe.throw(_("Interaction scope changed during read."), frappe.PermissionError)
	return {
		"contract_version": CONTRACT_VERSION,
		"items": [_summary(dict(row)) for row in page],
		"next_cursor": _encode_cursor(dict(page[-1])) if len(rows) > page_size and page else None,
	}


@frappe.whitelist()
def get_interaction_detail(interaction: str) -> dict[str, Any]:
	"""Return durable facts, analysis state, intents and score effects."""
	doc = _require_interaction(interaction)
	intents = frappe.get_list(
		"CRM Intent",
		filters={"interaction": doc.name},
		fields=[
			"name",
			"intent_type",
			"intent_role",
			"polarity",
			"importance",
			"confidence",
			"analysis_result",
			"notes",
			"modified",
		],
		order_by="modified desc, name desc",
	)
	scores = frappe.get_list(
		"CRM Score History",
		filters={"triggered_by_doctype": "CRM Interaction", "triggered_by": doc.name},
		fields=[
			"name",
			"source_score_input_revision",
			"policy_revision",
			"policy_hash",
			"scoring_time",
			"final_score",
			"score_change",
		],
		order_by="scoring_time desc, name desc",
		limit_page_length=20,
	)
	analysis = _safe_analysis(doc.name)
	evidence_refs = frappe.get_list(
		"CRM Interaction Evidence",
		filters={"interaction": doc.name, "source_revision": int(doc.source_revision or 0)},
		fields=["name", "actor_role", "evidence_kind", "occurred_at"],
		order_by="occurred_at asc, creation asc, name asc",
	)
	return {
		"contract_version": CONTRACT_VERSION,
		"interaction": _summary(doc.as_dict()),
		"revision": {
			"source_revision": int(doc.source_revision or 0),
			"evidence_digest": doc.evidence_digest or None,
		},
		"analysis": analysis,
		"intents": [
			{
				"id": row.name,
				"term_id": row.intent_type,
				"role": row.intent_role,
				"polarity": row.polarity,
				"importance": row.importance,
				"confidence": row.confidence,
				"analysis_result": row.analysis_result,
				"notes": row.notes or "",
				"modified_at": _iso(row.modified),
			}
			for row in intents
		],
		"score_effects": [
			{
				"id": row.name,
				"source_score_input_revision": int(row.source_score_input_revision or 0),
				"policy_revision": int(row.policy_revision or 0),
				"policy_hash": row.policy_hash or None,
				"scored_at": _iso(row.scoring_time),
				"final_score": row.final_score,
				"score_change": row.score_change,
			}
			for row in scores
		],
		"evidence_ref": doc.evidence or None,
		"evidence_refs": [
			{
				"id": row.name,
				"speaker_role": row.actor_role,
				"kind": row.evidence_kind,
				"occurred_at": _iso(row.occurred_at),
			}
			for row in evidence_refs
		],
	}


@frappe.whitelist()
def get_interaction_evidence(evidence: str, include_content: bool | str = False) -> dict[str, Any]:
	"""Resolve one evidence record after its parent Interaction scope check.

	Only explicitly privileged roles may dereference the raw body. Other scoped
	roles receive evidence metadata, never a best-effort regex-redacted version
	that could leave names or other personal data exposed.
	"""
	evidence = str(evidence or "").strip()
	if not evidence or not frappe.db.exists("CRM Interaction Evidence", evidence):
		frappe.throw(_("Evidence not found."), frappe.DoesNotExistError)
	doc = frappe.get_doc("CRM Interaction Evidence", evidence)
	parent = _require_interaction(doc.interaction)
	if doc.interaction != parent.name:
		frappe.throw(_("Evidence does not belong to the requested interaction."), frappe.PermissionError)
	can_read_raw = bool(set(frappe.get_roles(frappe.session.user)) & _EVIDENCE_CONTENT_ROLES)
	content = None
	include_content = _as_bool(include_content)
	if include_content and can_read_raw:
		content = doc.content
	return {
		"contract_version": CONTRACT_VERSION,
		"id": doc.name,
		"interaction": parent.name,
		"kind": doc.evidence_kind,
		"state": doc.evidence_state,
		"occurred_at": _iso(doc.occurred_at),
		"channel": doc.channel or None,
		"direction": doc.direction or None,
		"speaker_role": doc.actor_role or None,
		"content": content,
		"content_redacted": bool(include_content and not can_read_raw),
	}


def publish_interaction_invalidation(*, event_id: str) -> None:
	"""Publish an opaque post-commit invalidation; never evidence or interaction data."""
	token = hashlib.sha256(f"{event_id}:{frappe.generate_hash(length=16)}".encode()).hexdigest()
	frappe.publish_realtime(
		"crm_interaction_invalidated", {"event_id": event_id, "token": token}, after_commit=True
	)
