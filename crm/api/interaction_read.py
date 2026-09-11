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
from datetime import timedelta, timezone
from typing import Any

import frappe
from frappe import _
from frappe.utils import get_datetime

from crm.fcrm.interaction_semantics import INTERACTION_TYPE_MAPPING
from crm.fcrm.permissions import get_interaction_permission_query_conditions
from crm.fcrm.student_reference import canonical_student

CONTRACT_VERSION = "interaction.read:v1"
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
_EVIDENCE_CONTENT_ROLES = frozenset(
	{"Administrator", "System Manager", "CRM Manager", "Admissions Director"}
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


def _query_text(value: str | None, fieldname: str, *, max_length: int = 140) -> str | None:
	if not value:
		return None
	normalized = str(value).strip()
	if len(normalized) > max_length:
		frappe.throw(_(f"{fieldname} is too long."), frappe.ValidationError)
	return normalized or None


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


def _date_bound(value: str | None, fieldname: str, *, end: bool = False) -> tuple[Any, str | None]:
	if not value:
		return None, None
	value = str(value).strip()
	try:
		parsed = get_datetime(value)
	except (TypeError, ValueError):
		frappe.throw(_(f"Invalid {fieldname}."), frappe.ValidationError)
	if not parsed:
		frappe.throw(_(f"Invalid {fieldname}."), frappe.ValidationError)
	# Date-only `to_date` is inclusive for the whole calendar day.
	if end and len(value) == 10:
		return parsed + timedelta(days=1), "<"
	return parsed, "<=" if end else ">="


def _family_interaction_types(family: str | None) -> list[str] | None:
	if not family:
		return None
	normalized = " ".join(str(family).strip().casefold().replace("_", " ").split())
	matching_types = [
		interaction_type
		for interaction_type, semantic in INTERACTION_TYPE_MAPPING.items()
		if " ".join(str(semantic.get("purpose") or "").casefold().split()) == normalized
	]
	if not matching_types:
		frappe.throw(_("Invalid interaction family."), frappe.ValidationError)
	return matching_types


def _catalog_labels(doctype: str, names: list[str]) -> dict[str, str]:
	unique_names = sorted({str(name).strip() for name in names if name and str(name).strip()})
	if not unique_names:
		return {}
	rows = frappe.get_list(
		doctype,
		filters={"name": ["in", unique_names]},
		fields=["name", "display_name"],
		limit_page_length=len(unique_names),
	)
	return {row.name: row.display_name for row in rows if row.display_name}


def _analysis_states(interactions: list[str]) -> dict[str, str]:
	if not interactions:
		return {}
	runs = frappe.get_all(
		"CRM Interaction Analysis Run",
		filters={"interaction": ["in", interactions]},
		fields=["name", "interaction"],
		order_by="creation desc, name desc",
	)
	latest_runs: dict[str, str] = {}
	for run in runs:
		latest_runs.setdefault(run.interaction, run.name)
	if not latest_runs:
		return {}
	results = frappe.get_all(
		"CRM Interaction Analysis Result",
		filters={"analysis_run": ["in", list(latest_runs.values())]},
		fields=["analysis_run", "state"],
		order_by="creation desc, name desc",
	)
	states_by_run: dict[str, str] = {}
	for row in results:
		if row.state:
			states_by_run.setdefault(row.analysis_run, row.state)
	return {
		interaction: states_by_run[run_name]
		for interaction, run_name in latest_runs.items()
		if run_name in states_by_run
	}


def _require_target(*, student: str | None, contact: str | None) -> tuple[str, str]:
	student, contact = str(student or "").strip(), str(contact or "").strip()
	if bool(student) == bool(contact):
		frappe.throw(_("Provide exactly one Student or Contact."), frappe.ValidationError)
	student = canonical_student(student) if student else None
	contact = canonical_student(contact) if contact else None
	target_type, target = ("CRM Student", student) if student else ("CRM Student", contact)
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
			"contract_version",
			"decision_signals",
			"intelligence",
			"rule_version",
			"rule_version_digest",
			"ruleset_digest",
			"rule_decision",
			"intent",
			"terminal_reason",
		],
		order_by="creation desc",
	)
	return dict(rows[0]) if rows else None


def _summary(
	row: dict[str, Any],
	*,
	interaction_labels: dict[str, str] | None = None,
	analysis_states: dict[str, str] | None = None,
) -> dict[str, Any]:
	interaction_type = row.get("interaction_type")
	semantic = INTERACTION_TYPE_MAPPING.get(interaction_type, {})
	return {
		"id": row["name"],
		"occurred_at": _iso(row.get("interaction_datetime")),
		"interaction_type": interaction_type,
		"interaction_label": (interaction_labels or {}).get(interaction_type) or interaction_type,
		"channel": row.get("channel") or None,
		"direction": row.get("direction") or None,
		"outcome": row.get("outcome") or None,
		"summary": row.get("summary") or "",
		"episode_state": row.get("episode_state") or None,
		"analysis_state": (analysis_states or {}).get(row["name"]),
		"source_type": row.get("reference_doctype") or None,
		"source_id": row.get("reference_docname") or None,
		"semantic": {
			"channel": semantic.get("channel"),
			"purpose": semantic.get("purpose"),
			"disposition": semantic.get("disposition"),
			"is_direct_touchpoint": semantic.get("is_direct_touchpoint"),
			"evidence_kind": semantic.get("evidence_kind"),
		},
		"source_revision": int(row.get("source_revision") or 0),
		"has_evidence": bool(row.get("evidence")),
	}


def _score_effect(row: Any) -> dict[str, Any]:
	details = frappe.get_all(
		"CRM Score History Detail",
		filters={"parent": row.name},
		fields=["category", "rule_id", "signal", "score", "reason"],
		order_by="idx asc",
	)
	contributors = [
		{
			"category": detail.category,
			"rule_id": detail.rule_id,
			"signal": detail.signal,
			"score": detail.score,
			"reason": detail.reason or None,
		}
		for detail in details
		if detail.category or detail.rule_id or detail.signal or detail.reason
	]
	reasons = [detail["reason"] for detail in contributors if detail.get("reason")]
	source_key = row.get("triggered_by") or next(
		(
			detail.get("rule_id") or detail.get("signal")
			for detail in contributors
			if detail.get("rule_id") or detail.get("signal")
		),
		None,
	)
	return {
		"id": row.name,
		"source_score_input_revision": int(row.source_score_input_revision or 0),
		"policy_revision": int(row.policy_revision or 0),
		"policy_hash": row.policy_hash or None,
		"scored_at": _iso(row.scoring_time),
		"final_score": row.final_score,
		"score_change": row.score_change,
		"delta": row.score_change,
		"display_reason": "; ".join(reasons) if reasons else None,
		"source_key": source_key,
		"contributors": contributors[:6],
	}


@frappe.whitelist()
def list_interactions(
	student: str | None = None,
	contact: str | None = None,
	channel: str | None = None,
	direction: str | None = None,
	status: str | None = None,
	family: str | None = None,
	search: str | None = None,
	interaction_type: str | None = None,
	outcome: str | None = None,
	source_type: str | None = None,
	source_id: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	cursor: str | None = None,
	limit: int | str | None = None,
) -> dict[str, Any]:
	"""Return a stable, target-scoped Interaction feed without evidence."""
	_, target = _require_target(student=student, contact=contact)
	target_field = "student" if student else "crm_contact"
	conditions = [f"`{target_field}` = %(target)s"]
	values: dict[str, Any] = {"target": target}
	permission_condition = get_interaction_permission_query_conditions(
		user=frappe.session.user, doctype="CRM Interaction"
	)
	if permission_condition == "1=0":
		return {"contract_version": CONTRACT_VERSION, "items": [], "next_cursor": None}
	if permission_condition:
		conditions.append(f"({permission_condition})")
	for field, value in (
		("channel", channel),
		("direction", direction),
		("episode_state", status),
		("interaction_type", interaction_type),
		("outcome", outcome),
		("reference_doctype", source_type),
		("reference_docname", source_id),
	):
		if value:
			conditions.append(f"`{field}` = %({field})s")
			values[field] = str(value)
	search_text = _query_text(search, "search")
	if search_text:
		values["search"] = f"%{search_text}%"
		conditions.append(
			"(`summary` LIKE %(search)s OR `notes` LIKE %(search)s OR `outcome` LIKE %(search)s "
			"OR `interaction_type` LIKE %(search)s OR `channel` LIKE %(search)s "
			"OR `reference_doctype` LIKE %(search)s OR `reference_docname` LIKE %(search)s)"
		)
	family_types = _family_interaction_types(family)
	if family_types:
		family_params = []
		for index, interaction_type in enumerate(family_types):
			key = f"family_{index}"
			family_params.append(f"%({key})s")
			values[key] = interaction_type
		conditions.append(f"`interaction_type` IN ({', '.join(family_params)})")
	from_bound, from_operator = _date_bound(from_date, "from_date")
	to_bound, to_operator = _date_bound(to_date, "to_date", end=True)
	if from_bound and to_bound and from_bound > to_bound:
		frappe.throw(_("from_date must be before to_date."), frappe.ValidationError)
	if from_bound:
		conditions.append(f"`interaction_datetime` {from_operator} %(from_date)s")
		values["from_date"] = from_bound
	if to_bound:
		conditions.append(f"`interaction_datetime` {to_operator} %(to_date)s")
		values["to_date"] = to_bound
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
		"SELECT name, student, crm_contact, interaction_datetime, interaction_type, channel, direction, outcome, summary, episode_state, "
		"source_revision, evidence, reference_doctype, reference_docname "
		"FROM `tabCRM Interaction` WHERE "
		+ " AND ".join(conditions)
		+ " ORDER BY interaction_datetime DESC, name DESC LIMIT %(page_limit)s",
		values,
		as_dict=True,
	)
	page = rows[:page_size]
	# The target filter is necessary but not sufficient after joins/cursors.
	for row in page:
		if row.get("student" if student else "crm_contact") != target:
			frappe.throw(_("Interaction scope changed during read."), frappe.PermissionError)
	interaction_labels = _catalog_labels("CRM Interaction Type", [row.get("interaction_type") for row in page])
	analysis_states = _analysis_states([row["name"] for row in page])
	return {
		"contract_version": CONTRACT_VERSION,
		"items": [
			_summary(dict(row), interaction_labels=interaction_labels, analysis_states=analysis_states)
			for row in page
		],
		"next_cursor": _encode_cursor(dict(page[-1])) if len(rows) > page_size and page else None,
	}


@frappe.whitelist()
def get_interaction_detail(interaction: str) -> dict[str, Any]:
	"""Return durable facts, analysis state, intents and score effects."""
	doc = _require_interaction(interaction)
	# The parent Interaction has already passed the caller's row-scope check.
	# These are masked child projections, so re-checking the child DocPerm here
	# would make a valid Interaction reader depend on unrelated child grants.
	intents = frappe.get_all(
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
	scores = frappe.get_all(
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
			"triggered_by",
		],
		order_by="scoring_time desc, name desc",
		limit_page_length=20,
	)
	analysis = _safe_analysis(doc.name)
	interaction_labels = _catalog_labels("CRM Interaction Type", [doc.interaction_type])
	intent_labels = _catalog_labels("CRM Intent Type", [row.intent_type for row in intents])
	evidence_refs = frappe.get_all(
		"CRM Interaction Evidence",
		filters={"interaction": doc.name, "source_revision": int(doc.source_revision or 0)},
		fields=["name", "actor_role", "evidence_kind", "occurred_at"],
		order_by="occurred_at asc, creation asc, name asc",
	)
	return {
		"contract_version": CONTRACT_VERSION,
		"interaction": _summary(
			doc.as_dict(),
			interaction_labels=interaction_labels,
			analysis_states={doc.name: analysis.get("state")} if analysis else {},
		),
		"revision": {
			"source_revision": int(doc.source_revision or 0),
			"evidence_digest": doc.evidence_digest or None,
		},
		"analysis": analysis,
		"intents": [
			{
				"id": row.name,
				"term_id": row.intent_type,
				"semantic_key": row.intent_type,
				"display_name": intent_labels.get(row.intent_type) or row.intent_type,
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
		"score_effects": [_score_effect(row) for row in scores],
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
