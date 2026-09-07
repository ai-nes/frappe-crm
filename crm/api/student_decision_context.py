"""Least-privilege, bounded Decision Context projection for crm-agents v2."""

from __future__ import annotations

from datetime import timedelta
import re

import frappe

from crm.fcrm.interaction_semantics import resolve_interaction_type
from crm.fcrm.scoring_policy import get_active_policy
from crm.services.sales_action_policy import allowed_generation_actions, parent_authority_is_valid
from crm.services.student_context import snapshot_hash
from crm.services.student_next_task_policy import _journey_label, choose_next_task_policy
from crm.fcrm.student_contact_conversion import contacts_for_student

_STUDENT_FIELDS = [
	"name",
	"enrollment_status",
	"lifecycle_stage",
	"major",
	"current_grade",
	"study_stage",
	"branch",
	"province",
	"ward",
	"high_school",
	"assessment_status",
	"assessment_revision",
	"interest_level",
	"fit_level",
	"primary_barrier",
	"latest_score",
	"student_context_revision",
	"sla_evidence_state",
	"sla_evidence_observed_at",
	"score_input_revision",
	"applied_score_input_revision",
	"applied_policy_revision",
	"privacy_status",
]

_POLARITY_MAP = {
	"positive": "positive",
	"negative": "negative",
	"neutral": "neutral",
	"pos": "positive",
	"neg": "negative",
	"tích cực": "positive",
	"tiêu cực": "negative",
	"trung tính": "neutral",
}
_ENGAGEMENT_MAP = {
	"hot": "hot",
	"warm": "warm",
	"cooling": "cooling",
	"cold": "cold",
	"connected": "warm",
	"captured": "warm",
	"follow up needed": "cooling",
	# These values describe a business-result shaped field, not a reliable
	# interaction disposition.  Preserve that ambiguity instead of turning it
	# into engagement evidence for NBA.
	"resolved": "unknown",
	"converted": "unknown",
	"no response": "cooling",
	"data error": "unknown",
	"uncontactable": "cold",
	"bounced": "cold",
}

_INTERACTION_CHANNEL_MAP = {
	"call": "CALL",
	"phone": "CALL",
	"voice": "CALL",
	"email": "EMAIL",
	"e-mail": "EMAIL",
	"zalo": "MESSAGE",
	"message": "MESSAGE",
	"sms": "MESSAGE",
}

_CONSENT_SCOPE_CHANNELS = {
	"call": "CALL",
	"phone": "CALL",
	"telephone": "CALL",
	"voice": "CALL",
	"email": "EMAIL",
	"zalo": "MESSAGE",
	"message": "MESSAGE",
	"sms": "MESSAGE",
}

def _canonical_label(value, mapping: dict[str, str]) -> str:
	key = " ".join(str(value or "").strip().casefold().replace("_", " ").split())
	return mapping.get(key, "unknown")


def _application_projection(student: str) -> dict:
	"""Project application completeness from the authoritative application row."""
	rows = frappe.get_all(
		"CRM Admission Application",
		filters={"student": student},
		fields=["name", "status", "document_total", "document_completed", "deadline", "modified"],
		order_by="modified desc, name desc",
		limit_page_length=20,
		ignore_permissions=True,
	)
	if not rows:
		return {
			"completeness": "not_started",
			"missing": ["application"],
			"missing_count": 1,
			"source_revision": "none",
			"deadline": None,
		}
	# Prefer the newest non-terminal attempt; terminal rows are history, not a
	# live obligation for NBA.
	row = next(
		(item for item in rows if str(item.get("status") or "").casefold() not in {"enrolled", "lost", "withdrawn"}),
		rows[0],
	)
	status = " ".join(str(row.get("status") or "").strip().casefold().split())
	total = max(int(row.get("document_total") or 0), 0)
	completed = max(int(row.get("document_completed") or 0), 0)
	if total > 0 and completed >= total:
		completeness, missing_count = "complete", 0
	elif total > 0:
		completeness, missing_count = "partial", total - min(completed, total)
	elif status in {"draft", ""}:
		completeness, missing_count = "not_started", 1
	else:
		# Submitted/Under Review without document counts is not evidence of a
		# complete file; preserve the gap as an explicit unknown/partial signal.
		completeness, missing_count = "unknown", 0
	return {
		"completeness": completeness,
		"missing": ["required_documents"] if missing_count else [],
		"missing_count": missing_count,
		"source_revision": str(row.get("modified") or row.get("name") or "unknown"),
		"deadline": row.get("deadline"),
	}


def _academic_projection(student: str) -> dict:
	"""Resolve one bounded GPA, preferring the Student-owned table.

	A confirmed Student → Contact relation is only a compatibility fallback;
	multiple linked Contacts are ambiguous rather than an arbitrary source.
	Invalid/conflicting rows remain unknown/conflicting.
	"""
	fields = ["name", "school_year", "grade", "gpa", "modified", "idx"]
	rows = frappe.get_all(
		"CRM Student Academic Result",
		filters={"parent": student, "parenttype": "CRM Student"},
		fields=fields,
		order_by="modified desc, name desc",
		limit_page_length=100,
		ignore_permissions=True,
	)
	if not rows:
		contacts = contacts_for_student(student)
		if len(contacts) != 1:
			return {
				"gpa": None,
				"quality": "unknown",
				"source_revision": "ambiguous_contact" if contacts else "none",
				"evidence_ref": None,
			}
		rows = frappe.get_all(
			"CRM Student Academic Result",
			filters={"parent": contacts[0], "parenttype": "CRM Contact"},
			fields=fields,
			order_by="modified desc, name desc",
			limit_page_length=100,
			ignore_permissions=True,
		)
	if not rows:
		return {"gpa": None, "quality": "unknown", "source_revision": "none", "evidence_ref": None}
	def rank_row(row):
		grade = int(row.get("grade") or 0) if str(row.get("grade") or "").isdigit() else 0
		return (str(row.get("school_year") or ""), grade)

	latest_key = max((rank_row(row) for row in rows), default=("", 0))
	latest_rows = [row for row in rows if rank_row(row) == latest_key]
	valid = []
	for row in latest_rows:
		try:
			gpa = float(row.get("gpa"))
		except (TypeError, ValueError):
			continue
		if 0.0 <= gpa <= 10.0:
			valid.append((row, gpa))
	if not valid:
		return {"gpa": None, "quality": "unknown", "source_revision": "unknown", "evidence_ref": None}
	if len({round(gpa, 4) for _, gpa in valid}) != 1 or len(valid) != len(latest_rows):
		return {"gpa": None, "quality": "conflicting", "source_revision": "conflict", "evidence_ref": None}
	row, gpa = valid[0]
	return {
		"gpa": round(gpa, 2),
		"quality": "current",
		"source_revision": str(row.get("modified") or row.get("name") or "unknown"),
		"evidence_ref": f"academic_result:{row.get('name')}" if row.get("name") else None,
	}


def _consent_scope_channels(scope: object) -> set[str]:
	"""Map governed consent scopes to the NBA wire vocabulary.

	Only explicit channel tokens are accepted.  Purpose-only or legacy scopes
	remain fail-closed until a data-owner migration records their channels.
	"""
	normalized = str(scope or "").casefold().replace("e-mail", "email").replace("_", " ")
	tokens = set(re.findall(r"[\wÀ-ỹ]+", normalized, flags=re.UNICODE))
	return {channel for token, channel in _CONSENT_SCOPE_CHANNELS.items() if token in tokens}


def _contactability_projection(student: str) -> dict:
	"""Project contactability from append-only student/contact consent events.

	A preferred contact channel or a previous interaction proves neither consent
	nor permission for a future outreach.  Consent may target the Student or a
	legacy CRM Contact linked to that Student; both are authoritative producers
	for this student projection.  Missing or unknown scopes fail closed.
	Revocation events with an unscoped record revoke every channel.
	"""
	channels: set[str] = set()
	event_fields = ["name", "event_type", "scope", "occurred_at", "creation"]
	events = list(
		frappe.get_all(
			"CRM Contact Consent Event",
			filters={"student": student},
			fields=event_fields,
			limit_page_length=0,
			ignore_permissions=True,
		)
	)
	# The conversion junction is authoritative once present; its helper falls
	# back to the legacy Contact.student link only for unmigrated rows.
	contact_names = contacts_for_student(student)
	if contact_names:
		events.extend(
			frappe.get_all(
				"CRM Contact Consent Event",
				filters={"contact": ["in", contact_names]},
				fields=event_fields,
				limit_page_length=0,
				ignore_permissions=True,
			)
		)
	events.sort(
		key=lambda event: (
			str(event.get("occurred_at") or ""),
			str(event.get("creation") or ""),
			str(event.get("name") or ""),
		)
	)
	for event in events:
		event_type = str(event.get("event_type") or "").strip().casefold()
		scope_channels = _consent_scope_channels(event.get("scope"))
		if event_type in {"granted", "re-subscribed"}:
			channels.update(scope_channels)
		elif event_type in {"opted out", "suppressed", "bounced", "marked test"}:
			if scope_channels:
				channels.difference_update(scope_channels)
			else:
				channels.clear()
	return {
		"consent": bool(channels),
		"channels": sorted(channels),
		# The agent never receives a Contact identifier.  It only needs to know
		# whether Frappe resolved one executable recipient for a channel action.
		"recipient_bound": len(contact_names) == 1,
	}


def _require_agent_identity():
	if frappe.session.user == "Guest":
		frappe.throw("Authentication is required.", frappe.PermissionError)
	if frappe.session.user == "Administrator":
		return
	configured = frappe.conf.get("crm_agents_service_user")
	if not configured or frappe.session.user != configured:
		frappe.throw(
			"This endpoint is restricted to the crm-agents service identity.", frappe.PermissionError
		)


def _intent_provenance(intent: dict, student: str) -> dict:
	"""Bounded source-interaction reference for the dominant CRM Intent row.

	`interaction` is `reqd=1` on CRM Intent (crm_intent.json) for every new
	row, so a null value here can only mean a pre-existing row saved before
	that constraint existed — represent that explicitly as "legacy_missing"
	rather than fabricating a reference or silently omitting provenance.
	"""
	if not intent:
		return {"state": "none", "interaction": None}
	interaction_name = intent.get("interaction")
	if not interaction_name:
		return {"state": "legacy_missing", "interaction": None}
	source = frappe.db.get_value(
		"CRM Interaction",
		{"name": interaction_name, "student": student},
		["interaction_type", "interaction_datetime"],
		as_dict=True,
	)
	if not source:
		# The link is set but its target CRM Interaction row is gone (deleted,
		# never existed, or — on dirty data — belongs to a different student,
		# which must never be exposed as this student's evidence) — distinct
		# from a genuinely absent link.
		return {"state": "stale_reference", "interaction": None}
	canonical = resolve_interaction_type(source.interaction_type)
	return {
		"state": "linked",
		"interaction": {
			"id": interaction_name,
			"channel": canonical["channel"] if canonical else None,
			"purpose": canonical["purpose"] if canonical else None,
			"disposition": canonical["disposition"] if canonical else None,
			"at": source.interaction_datetime,
		},
	}


def _interaction_recency(interaction: dict, *, at=None) -> int | None:
	"""Whole days since the most recent interaction, or None when there is none.

	This is a "why now" signal for the decision layer: silence duration is a
	first-class input to Next Best Action, independent of any 360 analysis.
	"""
	interaction_at = interaction.get("interaction_datetime")
	if not interaction_at:
		return None
	delta = (at or frappe.utils.now_datetime()) - frappe.utils.get_datetime(interaction_at)
	return max(delta.days, 0)


def _intent_observation_count(student: str, intent_type: str | None) -> int:
	"""How many times the dominant intent has been observed for this student.

	A repeated intent is a stronger signal than a one-off. Bounded count only,
	never the intent rows themselves.
	"""
	if not intent_type:
		return 0
	return frappe.db.count("CRM Intent", {"student": student, "intent_type": intent_type})


def _days_to_deadline(student: str, *, at=None) -> int | None:
	"""Whole days until the nearest open admission-application deadline.

	A hard "why now" signal and the override the WAIT pre-check needs: a looming
	cut-off outranks "we spoke recently". Only non-terminal applications count;
	an already Enrolled/Lost/Withdrawn row carries no live obligation. Negative
	when the deadline is already past.
	"""
	rows = frappe.get_all(
		"CRM Admission Application",
		filters={
			"student": student,
			"status": ["not in", ["Enrolled", "Lost", "Withdrawn"]],
			"deadline": ["is", "set"],
		},
		fields=["deadline"],
		order_by="deadline asc",
		limit_page_length=1,
		ignore_permissions=True,
	)
	if not rows or not rows[0].get("deadline"):
		return None
	delta = frappe.utils.getdate(rows[0]["deadline"]) - frappe.utils.getdate(at or frappe.utils.now_datetime())
	return delta.days


def _recent_actions(student: str) -> list[dict]:
	"""The last few CRM Actions for this student — action-history context only.

	Canonical semantic fields (type, state, outcome, timestamp) — no objective
	text, no package content, no PII. Lets the decision layer see what was
	already tried and avoid recommending a duplicate move.
	"""
	rows = frappe.get_all(
		"CRM Action Item",
		filters={"student": student},
		fields=["action", "action_type", "state", "execution_status", "disposition", "creation", "outcome_code"],
		order_by="creation desc",
		limit_page_length=5,
		ignore_permissions=True,
	)
	return [
		{
			# CRM Action Item stores the stable NBA action code in ``action`` and
			# its broad UI category in ``action_type``.  The decision kernel uses
			# this field to detect an in-flight action by code, so never project
			# the category when the canonical code is available.
			"action_type": row.get("action") or row.get("action_type"),
			# The broad UI category on its own -- lets opportunity suppression
			# require the closing action to actually be in the opportunity's own
			# domain (e.g. APPLICATION), not just be the latest action taken.
			"action_category": row.get("action_type"),
			"state": row.get("state"),
			"execution_status": row.get("execution_status"),
			"disposition": row.get("disposition"),
			"at": str(row.get("creation")) if row.get("creation") else None,
			"outcome_code": row.get("outcome_code"),
		}
		for row in rows
	]


def _score_projection(row: dict) -> dict:
	"""Additive score evidence: `freshness` mirrors the same
	(score_input_revision, policy_revision) tuple ordering
	`append_score_if_current` already uses for its CAS write, so a consumer
	never needs to duplicate that comparison logic to know whether the
	last-written score reflects the student's current facts and policy.
	`required_revision` is always None today -- no Recommendation/RCM rule yet
	declares "fresh score mandatory"; it is reserved so a future rule can
	populate it without another contract change.
	"""
	policy = get_active_policy() or {}
	policy_revision = int(policy.get("policy_revision") or 0)
	policy_hash = policy.get("policy_hash") or ""
	current_revision = int(row.get("score_input_revision") or 0)
	applied_input_revision = int(row.get("applied_score_input_revision") or 0)
	applied_policy_revision = int(row.get("applied_policy_revision") or 0)
	if row.get("latest_score") is None:
		freshness = "unknown"
	elif (applied_input_revision, applied_policy_revision) >= (current_revision, policy_revision):
		freshness = "current"
	else:
		freshness = "pending"
	return {
		"current": row.get("latest_score"),
		"freshness": freshness,
		"current_revision": current_revision,
		"required_revision": None,
		"policy_revision": policy_revision,
		"policy_hash": policy_hash,
	}


def _projection(student: str, minimum_revision: int, *, service_authorized: bool = False, at=None) -> dict:
	"""Build the bounded decision DTO.

	``service_authorized`` is deliberately private and is only used by Frappe's
	service-only Intelligence Run authority after it has checked its caller.
	Reader-facing calls must continue to pass the normal Student permission
	check below.
	"""
	row = frappe.db.get_value("CRM Student", student, _STUDENT_FIELDS, as_dict=True)
	if not row:
		frappe.throw("Student not found.", frappe.DoesNotExistError)
	if not service_authorized and not frappe.has_permission("CRM Student", "read", student, throw=False):
		frappe.throw("Student projection is not authorized.", frappe.PermissionError)
	revision = int(row.student_context_revision or 0)
	if revision < int(minimum_revision):
		frappe.throw("Requested Student revision is not available.", frappe.ValidationError)
	intent = (
		frappe.db.get_value(
			"CRM Intent",
			{"student": student},
			["intent_type", "importance", "confidence", "polarity", "interaction"],
			order_by="creation desc",
			as_dict=True,
		)
		or {}
	)
	intent_provenance = _intent_provenance(intent, student)
	interaction = (
		frappe.db.get_value(
			"CRM Interaction",
			{"student": student},
			["interaction_type", "outcome", "interaction_datetime"],
			order_by="interaction_datetime desc",
			as_dict=True,
		)
		or {}
	)
	application = _application_projection(student)
	academic = _academic_projection(student)
	contactability = _contactability_projection(student)
	sla_state = row.sla_evidence_state or "unknown"
	evaluated_at = at or frappe.utils.now_datetime()
	if (
		row.sla_evidence_observed_at
		and row.sla_evidence_observed_at < evaluated_at - timedelta(minutes=5)
	):
		sla_state = "stale"
	# Do not add names, phones, emails, raw notes, or free text to this DTO.
	context = {
		"student_id": student,
		"returned_revision": revision,
		"policy_version": "student-next-task-v2",
		"eligibility": {"student": True},
		"lifecycle": {
			"stage": row.lifecycle_stage or row.enrollment_status,
		},
		"study": {
			"current_grade": row.current_grade,
			"stage": row.study_stage,
			"high_school": row.high_school,
			"province": row.province,
			"ward": row.ward,
		},
		"assessment": {
			"status": row.assessment_status,
			"revision": int(row.assessment_revision or 0),
			"interest": row.interest_level,
			"fit": row.fit_level,
			"primary_barrier": row.primary_barrier,
		},
		"intent": {
			"type": intent.get("intent_type"),
			"importance": intent.get("importance"),
			"confidence": intent.get("confidence"),
			"polarity": _canonical_label(intent.get("polarity"), _POLARITY_MAP),
			"count": _intent_observation_count(student, intent.get("intent_type")),
			"provenance": intent_provenance,
		},
		"score": _score_projection(row),
		"interaction": {
			"channel": (
				_INTERACTION_CHANNEL_MAP.get(
					str((resolve_interaction_type(interaction.get("interaction_type")) or {}).get("channel") or "").casefold()
				)
				or "unknown"
			),
			"outcome": _canonical_label(interaction.get("outcome"), _ENGAGEMENT_MAP),
			"at": interaction.get("interaction_datetime"),
			"days_since": _interaction_recency(interaction, at=evaluated_at),
		},
		"sla_evidence": {
			"state": sla_state,
			"observed_at": row.sla_evidence_observed_at,
		},
		"allowed_action_types": allowed_generation_actions(student),
		"recent_actions": _recent_actions(student),
		"evidence_refs": [],
		"application": application,
		"academic": academic,
		"contactability": contactability,
		"parent_authority": {"valid": bool(parent_authority_is_valid(student))},
	}
	allowed_actions = context["allowed_action_types"]
	parent_authorized = parent_authority_is_valid(student)
	stage = context["lifecycle"]["stage"]
	eligible = str(stage or "").casefold() not in {"lost", "enrolled", "đã xác nhận", "closed"}
	action, objective, actionable = choose_next_task_policy(
		intent.get("intent_type"),
		stage,
		allowed_actions,
		eligible=eligible,
		parent_authorized=parent_authorized,
	)
	context["eligibility"]["student"] = eligible
	context["eligibility"]["actionable"] = actionable
	context["lifecycle"].update(
		{
			"next_task_action": action,
			"next_task_objective": objective,
			"stage_label": _journey_label(stage),
			"days_to_deadline": _days_to_deadline(student, at=evaluated_at),
		}
	)
	context["evidence_refs"] = [
		f"student-context:revision:{revision}:intent",
		f"student-context:revision:{revision}:stage",
		f"score-input:revision:{context['score']['current_revision']}:score",
	]
	if academic.get("quality") == "current" and academic.get("evidence_ref"):
		context["evidence_refs"].append(str(academic["evidence_ref"]))
	if action in {"PARENT_CONTACT", "CONTACT_PARENT"}:
		context["evidence_refs"].append(f"student-context:revision:{revision}:parent-authority")
	hash_input = {key: value for key, value in context.items() if key not in {"student_id"}}
	context["snapshot_hash"] = snapshot_hash(hash_input)
	return context


@frappe.whitelist()
def get_student_decision_context(student: str, minimum_revision: int = 0, rollout_epoch: int = 0) -> dict:
	_require_agent_identity()
	return _projection(student, int(minimum_revision), service_authorized=True)


@frappe.whitelist()
def get_execution_personalization_context(task: str, action: str | None = None) -> dict:
	"""Separate accepted-task context; never usable for task selection."""
	if frappe.session.user == "Guest":
		frappe.throw("Authentication is required.", frappe.PermissionError)
	task_row = frappe.db.get_value(
		"CRM Action Item",
		task,
		["name", "student", "state", "action", "action_type", "action_revision", "execution_package_version"],
		as_dict=True,
	)
	if not task_row or task_row.state not in {"accepted", "in-progress", "requires-review"}:
		frappe.throw("Execution context requires an accepted task.", frappe.ValidationError)
	if not frappe.has_permission("CRM Student", "read", task_row.student, throw=False):
		frappe.throw("Task is outside the actor's Student scope.", frappe.PermissionError)
	return {
		"task": task_row.name,
		"student": task_row.student,
		"action": task_row.action,
		"action_type": task_row.action_type,
		"action_revision": task_row.action_revision,
		"package_revision": task_row.execution_package_version,
		"recipient": {"source": "Frappe command authorization"},
		"evidence_refs": [],
	}
