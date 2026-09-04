"""Frappe authority for durable, scoped Intelligence Runs.

This is deliberately the only place that creates parent runs and stages.  The
agent service receives an identity-only outbox signal, then asks Frappe for
fresh bounded evidence and settles a fenced stage result.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import frappe
from frappe.utils import add_to_date, now_datetime

from crm.fcrm.analysis_runs import canonical_request_fingerprint, validate_claim_set, validate_execution_revisions
from crm.fcrm.school_intelligence import get_school_intelligence

SERVICE_USER_KEY = "crm_agents_service_user"
RUN_TYPES = {"student": "CRM Student Analysis Run", "school": "CRM School Analysis Run"}
STAGES = {"student": ("student_360",), "school": ("school_360",)}
TERMINAL = {"completed", "abstained", "failed", "dead_lettered"}
ACTIVE = {"queued", "running"}
PROVENANCE_DOCTYPES = {
	"student": "CRM Student",
	"school": "CRM High School",
	"snapshot": "CRM High School Annual Snapshot",
	"stakeholder": "CRM School Stakeholder",
	"activity": "CRM School Activity",
	# School activities own their outcome fields.  ``outcome:<activity>`` is a
	# resolvable provenance alias, not a fictional outcome DocType.
	"outcome": "CRM School Activity",
}


def _service_only():
	if frappe.session.user != frappe.conf.get(SERVICE_USER_KEY):
		frappe.throw("This command is restricted to the crm-agents service identity.", frappe.PermissionError)


def _lease_now() -> datetime:
	"""Use a naive UTC clock at the MariaDB Datetime boundary.

	Frappe site timezone may be local while the Docker MariaDB session is UTC;
	passing local aware values otherwise shifts leases hours into the future.
	"""
	return datetime.now(timezone.utc).replace(tzinfo=None)


def _digest(value: Any) -> str:
	return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _target(domain: str, target: str):
	if domain not in RUN_TYPES or not target:
		frappe.throw("Invalid Intelligence Run target.", frappe.ValidationError)
	doctype = "CRM Student" if domain == "student" else "CRM High School"
	if not frappe.db.exists(doctype, target):
		frappe.throw("Intelligence Run target does not exist.", frappe.DoesNotExistError)
	if not frappe.has_permission(doctype, "read", target):
		frappe.throw("Intelligence Run target is outside current scope.", frappe.PermissionError)


def _source(domain: str, target: str, admission_year: int | None = None) -> tuple[str, str]:
	if domain == "student":
		revision = str(int(frappe.db.get_value("CRM Student", target, "student_context_revision") or 0))
		return revision, _digest({"student": target, "revision": revision})
	# Never hash ``get_school_intelligence`` here.  That is a reader projection
	# and deliberately changes with the caller's permissions.  A run identity is
	# service-owned: the school aggregate's monotonic journal revision is the
	# authoritative snapshot cursor, while permission filtering happens only when
	# a persisted claim is rendered to a reader.
	journal_revision = str(int(frappe.db.get_value("CRM High School", target, "intelligence_revision") or 0))
	return journal_revision, _digest({"domain": "school", "high_school": target, "revision": journal_revision, "admission_year": admission_year or None})


def _lock_target(domain: str, target: str) -> None:
	"""Serialize run creation for one aggregate until schema-level uniqueness wins."""
	doctype = "CRM Student" if domain == "student" else "CRM High School"
	frappe.db.sql(f"SELECT name FROM `tab{doctype}` WHERE name=%s FOR UPDATE", (target,))


def _parent_status(run_type: str, parent_run: str) -> str:
	statuses = frappe.get_all("CRM Analysis Run Stage", filters={"parent_run_type": run_type, "parent_run": parent_run}, pluck="status")
	if statuses and all(status in TERMINAL for status in statuses):
		if all(status == "completed" for status in statuses):
			return "completed"
		if "failed" in statuses:
			return "failed"
		if "dead_lettered" in statuses:
			return "dead_lettered"
		return "abstained"
	return "running" if "running" in statuses else "queued"


def _receipt(receipt) -> dict[str, Any]:
	run = frappe.get_doc(receipt.parent_run_type, receipt.parent_run)
	stages = frappe.get_all("CRM Analysis Run Stage", filters={"parent_run_type": receipt.parent_run_type, "parent_run": receipt.parent_run}, fields=["name", "stage_kind", "status", "claims", "report_json", "policy_revision", "model_revision", "terminal_reason"])
	for stage in stages:
		stage["claims"] = visible_claims(stage.get("claims"))
		stage["report"] = frappe.parse_json(stage["report_json"]) if stage.get("report_json") else None
		stage.pop("report_json", None)
	return {"receipt": receipt.name, "run_id": run.name, "run_type": receipt.parent_run_type, "status": run.status, "stages": stages}


def unified_intelligence_enabled() -> bool:
	"""Require producer cutover and the fenced NBA writer as one state.

	Enabling only the producer would leave the legacy writer available; enabling
	only the writer safely quiesces legacy generation.  A unified run is allowed
	only after both settings are deliberately present.
	"""
	return (
		frappe.conf.get("crm_intelligence_runs_enabled", 0) in (1, "1", True)
		and frappe.conf.get("crm_intelligence_writer_epoch") is not None
	)


def require_unified_intelligence_enabled() -> None:
	if not unified_intelligence_enabled():
		frappe.throw("Unified Intelligence Run cutover is not enabled.", frappe.ValidationError)


def read_receipt(request_id: str) -> dict[str, Any]:
	"""Resolve a requester-owned receipt without ambiguous parent run IDs."""
	receipt = frappe.get_doc("CRM Analysis Request Receipt", request_id)
	if receipt.requester != frappe.session.user:
		frappe.throw("Analysis request receipt is outside current scope.", frappe.PermissionError)
	if receipt.get("expires_at") and receipt.expires_at <= now_datetime():
		frappe.throw("Analysis request receipt has expired.", frappe.DoesNotExistError)
	run = frappe.get_doc(receipt.parent_run_type, receipt.parent_run)
	target_type, target = (
		("CRM Student", run.student)
		if receipt.parent_run_type == RUN_TYPES["student"]
		else ("CRM High School", run.high_school)
	)
	if not frappe.has_permission(target_type, "read", target):
		frappe.throw("Analysis request receipt is outside current scope.", frappe.PermissionError)
	return _receipt(receipt)


def _claim_visible(provenance_ids: list[str]) -> bool:
	"""Fail closed unless every cited source remains visible to this reader."""
	for source in provenance_ids:
		prefix, separator, name = str(source).partition(":")
		doctype = PROVENANCE_DOCTYPES.get(prefix)
		if not separator or not doctype or not name or not frappe.db.exists(doctype, name):
			return False
		if not frappe.has_permission(doctype, "read", name):
			return False
	return True


def visible_claims(claims) -> list[dict[str, Any]]:
	"""Return only whole claims whose complete evidence set is still readable."""
	parsed = frappe.parse_json(claims) if isinstance(claims, str) else (claims or [])
	return [claim for claim in parsed if isinstance(claim, dict) and _claim_visible(claim.get("provenance_ids") or [])]


def _manual_request_limit() -> tuple[int, int]:
	"""Return bounded anti-click-spam policy, configurable without code changes."""
	return (
		max(1, int(frappe.conf.get("crm_intelligence_manual_requests_per_actor_target", 3) or 3)),
		max(1, int(frappe.conf.get("crm_intelligence_manual_request_window_minutes", 60) or 60)),
	)


def _require_force_rerun_permission(reason: str | None) -> str | None:
	if reason is None:
		return None
	reason = str(reason).strip()
	if len(reason) < 10 or len(reason) > 500:
		frappe.throw("Forced reruns require a reason between 10 and 500 characters.", frappe.ValidationError)
	roles = set(frappe.get_roles(frappe.session.user))
	configured = frappe.conf.get("crm_intelligence_force_rerun_roles") or ["System Manager"]
	if isinstance(configured, str):
		configured = [role.strip() for role in configured.split(",")]
	if not roles.intersection(set(configured)):
		frappe.throw("Current user may not force an Intelligence Run rerun.", frappe.PermissionError)
	return reason


def _enforce_manual_quota(domain: str, target: str) -> None:
	limit, window_minutes = _manual_request_limit()
	window_start = add_to_date(now_datetime(), minutes=-window_minutes)
	run_type = RUN_TYPES[domain]
	field = "student" if domain == "student" else "high_school"
	count = frappe.db.count(
		run_type,
		filters={field: target, "trigger": "manual", "requested_by": frappe.session.user, "creation": [">=", window_start]},
	)
	if count >= limit:
		frappe.throw("Manual Intelligence Run limit reached for this target; try again later.", frappe.ValidationError)


def _active_run(domain: str, target: str):
	run_type = RUN_TYPES[domain]
	field = "student" if domain == "student" else "high_school"
	runs = frappe.get_all(
		run_type,
		filters={field: target, "status": ["in", sorted(ACTIVE)]},
		pluck="name",
		order_by="creation asc",
		limit_page_length=2,
	)
	if len(runs) > 1:
		frappe.throw("Intelligence Run active-run invariant is violated; operator repair is required.", frappe.ValidationError)
	return frappe.get_doc(run_type, runs[0]) if runs else None


def request_run(*, domain: str, target: str, idempotency_key: str, force_reason: str | None = None, admission_year: int | None = None) -> dict[str, Any]:
	"""Create/reuse a scoped manual run; no caller credential is persisted."""
	require_unified_intelligence_enabled()
	_target(domain, target)
	# The aggregate row is the mutex for button-click races.  This covers the
	# interval before the unique automatic identity below is available on sites
	# that have not migrated yet.
	_lock_target(domain, target)
	key = str(idempotency_key or "").strip()
	if not key or len(key) > 140:
		frappe.throw("Idempotency-Key is required and bounded.", frappe.ValidationError)
	force_reason = _require_force_rerun_permission(force_reason)
	revision, source_digest = _source(domain, target, admission_year)
	payload = {"domain": domain, "target": target, "source_revision": revision, "trigger": "manual"}
	if force_reason:
		payload["force_reason"] = str(force_reason).strip()
	fingerprint = canonical_request_fingerprint(payload)
	existing = frappe.db.get_value("CRM Analysis Request Receipt", {"idempotency_key": key}, "name")
	if existing:
		receipt = frappe.get_doc("CRM Analysis Request Receipt", existing)
		if receipt.requester != frappe.session.user:
			frappe.throw("Idempotency-Key belongs to another requester.", frappe.PermissionError)
		if receipt.request_fingerprint != fingerprint:
			frappe.throw("Idempotency-Key was already used for a different request.", frappe.ValidationError)
		return _receipt(receipt)
	run_type = RUN_TYPES[domain]
	active_run = _active_run(domain, target)
	if active_run:
		# A force flag never bypasses the single-active-run fence.  It is for a
		# completed/abstained revision whose analyst needs an auditable rerun.
		run = active_run
	elif not force_reason:
		# A normal button press is a request for the current analysis, not an
		# instruction to spend another model call.  Reuse any terminal result for
		# precisely this authoritative revision; an explicit privileged force is
		# the only way to rerun it.
		field = "student" if domain == "student" else "high_school"
		matching_terminal = frappe.get_all(
			run_type,
			filters={field: target, "source_revision": revision, "source_digest": source_digest, "status": ["in", sorted(TERMINAL)]},
			pluck="name",
			order_by="creation desc",
			limit_page_length=1,
		)
		run = frappe.get_doc(run_type, matching_terminal[0]) if matching_terminal else None
		if not run:
			_enforce_manual_quota(domain, target)
			run = _insert_run(domain, target, revision, source_digest, fingerprint, admission_year)
	else:
		_enforce_manual_quota(domain, target)
		run = _insert_run(domain, target, revision, source_digest, fingerprint, admission_year)
	receipt = frappe.get_doc({"doctype": "CRM Analysis Request Receipt", "requester": frappe.session.user, "idempotency_key": key, "request_fingerprint": fingerprint, "parent_run_type": run_type, "parent_run": run.name, "expires_at": add_to_date(now_datetime(), hours=24)}).insert(ignore_permissions=True)
	# An existing active run already has durable work.  Re-emitting its event is
	# safe but unnecessary and would amplify a click storm.
	if not active_run and run.status == "queued":
		from crm.api.agent_events import record_intelligence_run_event
		record_intelligence_run_event(run)
	return _receipt(receipt)


def request_automatic_run(domain: str, target: str, admission_year: int | None = None, admission_decision: str | None = None, admission_event: str | None = None, candidate_revision: int | None = None, policy_revision: str | None = None):
	"""Create one idempotent automatic parent for an authoritative revision."""
	require_unified_intelligence_enabled()
	if domain not in RUN_TYPES:
		raise ValueError("invalid Intelligence Run domain")
	_lock_target(domain, target)
	revision, source_digest = _source(domain, target, admission_year)
	run_type = RUN_TYPES[domain]
	field = "student" if domain == "student" else "high_school"
	existing = frappe.get_all(run_type, filters={field: target, "source_revision": revision, "source_digest": source_digest, "trigger": "automatic"}, pluck="name", limit_page_length=1)
	if existing:
		return frappe.get_doc(run_type, existing[0])
	fingerprint = canonical_request_fingerprint({"domain": domain, "target": target, "source_revision": revision, "trigger": "automatic"})
	try:
		run = _insert_run(domain, target, revision, source_digest, fingerprint, admission_year, trigger="automatic", admission_decision=admission_decision, admission_event=admission_event, candidate_revision=candidate_revision, policy_revision=policy_revision)
	except Exception as exc:
		# A composite identity cannot be represented in old Frappe metadata.  New
		# sites enforce ``automatic_identity`` uniquely; retain a safe lookup for
		# a concurrent winner and re-raise every unrelated insert error.
		if "duplicate" not in str(exc).casefold() and "unique" not in str(exc).casefold():
			raise
		existing = frappe.db.get_value(run_type, {"automatic_identity": _automatic_identity(domain, target, revision, source_digest, admission_year)}, "name")
		if not existing:
			raise
		return frappe.get_doc(run_type, existing)
	from crm.api.agent_events import record_intelligence_run_event
	record_intelligence_run_event(run)
	return run


def _insert_run(domain, target, revision, source_digest, fingerprint, admission_year, *, trigger="manual", admission_decision=None, admission_event=None, candidate_revision=None, policy_revision=None):
	run_type = RUN_TYPES[domain]
	values = {"doctype": run_type, "source_revision": revision, "source_digest": source_digest, "trigger": trigger, "status": "queued", "request_fingerprint": fingerprint}
	if trigger == "manual":
		values["requested_by"] = frappe.session.user
	values["student" if domain == "student" else "high_school"] = target
	if trigger == "automatic":
		values["automatic_identity"] = _automatic_identity(domain, target, revision, source_digest, admission_year)
		values.update({"admission_decision": admission_decision, "admission_event": admission_event, "candidate_revision": candidate_revision if candidate_revision is not None else revision, "policy_revision": policy_revision})
	if domain == "school":
		values["admission_year"] = admission_year
	run = frappe.get_doc(values).insert(ignore_permissions=True)
	for stage_kind in STAGES[domain]:
		frappe.get_doc({"doctype": "CRM Analysis Run Stage", "parent_run_type": run_type, "parent_run": run.name, "stage_kind": stage_kind, "stage_key": f"{run_type}:{run.name}:{stage_kind}", "status": "queued", "stage_generation": 0, "expected_source_revision": revision, "expected_source_digest": source_digest}).insert(ignore_permissions=True)
	return run


def _automatic_identity(domain: str, target: str, revision: str, source_digest: str, admission_year: int | None) -> str:
	"""Stable DB-unique identity for one automatic analysis of one source."""
	return _digest({"domain": domain, "target": target, "revision": str(revision), "digest": source_digest, "admission_year": admission_year or None, "trigger": "automatic"})


def _student_stage_evidence(student: str, revision: str) -> dict[str, Any]:
	"""Return the bounded, no-PII evidence surface used by both Student stages."""
	from crm.api.student_decision_context import _projection

	decision = _projection(student, int(revision))
	# The NBA handler uses the strict V2 projection.  Do not let display-only
	# fields grow this service contract or leak through an accidental model dump.
	decision_context = {
		key: decision.get(key)
		for key in (
			"student_id", "returned_revision", "snapshot_hash", "policy_version",
			"eligibility", "lifecycle", "intent", "score", "interaction",
			"sla_evidence", "allowed_action_types", "recent_actions",
		)
	}
	decision_context["evidence_refs"] = [f"student:{student}"]
	row = frappe.db.get_value(
		"CRM Student", student,
		[
			"lifecycle_stage", "enrollment_status", "current_grade", "study_stage",
			"assessment_status", "interest_level", "fit_level", "primary_barrier",
			"latest_score", "sla_evidence_state",
		],
		as_dict=True,
	) or {}
	# Context packs are bounded and intentionally exclude names, contact data,
	# notes, summaries and linked document identifiers.  They provide the model
	# the temporal/decision context needed for a useful 360 analysis while
	# preserving the service-only permission boundary.
	def _rows(doctype, fields, limit, order_by="modified desc"):
		if not frappe.db.table_exists(doctype):
			return []
		return frappe.get_all(doctype, filters={"student": student}, fields=fields,
			limit_page_length=limit, order_by=order_by, ignore_permissions=True)

	score_history = _rows("CRM Score History", [
		"scoring_time", "scoring_date", "final_score", "score_change", "fit_score",
		"engagement_score", "intent_score",
	], 12, "scoring_time desc, creation desc")
	# Legacy score rows may only have scoring_time.  The agent evidence contract
	# requires a bounded temporal reference, so normalize at the producer edge.
	for item in score_history:
		item["scoring_date"] = str(item.get("scoring_date") or item.get("scoring_time") or "unknown")
		item.pop("scoring_time", None)
	interactions = _rows("CRM Interaction", [
		"interaction_datetime", "channel", "direction", "outcome", "source_verified",
	], 20, "interaction_datetime desc, creation desc")
	applications = _rows("CRM Admission Application", [
		"status", "preference", "preference_order", "document_total",
		"document_completed", "scholarship_percentage", "deadline",
	], 8, "modified desc")
	guardians = _rows("CRM Student Guardian", [
		"relationship", "decision_role", "involvement", "preferred_channel", "is_active",
	], 8, "modified desc")
	lifecycle = _rows("CRM Student Lifecycle Event", [
		"from_stage", "to_stage", "transition_kind", "occurred_at",
	], 20, "occurred_at desc, creation desc")
	# This is evidence, not a conclusion: the AI handler must derive and label
	# any inference/uncertainty it publishes.  No name, phone, email, notes,
	# free-form interaction text, or recipient data crosses this boundary.
	student_360 = {
		"signals": {
			"lifecycle_stage": row.get("lifecycle_stage") or row.get("enrollment_status"),
			"study_stage": row.get("study_stage") or row.get("current_grade"),
			"assessment_status": row.get("assessment_status"),
			"interest": row.get("interest_level"),
			"fit": row.get("fit_level"),
			"primary_barrier": row.get("primary_barrier"),
			"score": row.get("latest_score"),
		# The decision projection uses ``pending`` while a score is being
		# calculated; the analysis evidence contract intentionally exposes only
		# its bounded freshness vocabulary.
		"score_freshness": {
			"current": "fresh",
			"fresh": "fresh",
			"stale": "stale",
			"pending": "unknown",
			"unknown": "unknown",
			"unavailable": "unavailable",
		}.get((decision.get("score") or {}).get("freshness"), "unknown"),
			"intent_type": (decision.get("intent") or {}).get("type"),
			"intent_polarity": (decision.get("intent") or {}).get("polarity"),
			"latest_interaction_outcome": (decision.get("interaction") or {}).get("outcome"),
			"sla_state": row.get("sla_evidence_state") or (decision.get("sla_evidence") or {}).get("state"),
			"score_history": [
				{
					"scoring_date": item.get("scoring_date") or item.get("scoring_time"),
					"final_score": item.get("final_score"),
					"score_change": item.get("score_change"),
					"fit_score": item.get("fit_score"),
					"engagement_score": item.get("engagement_score"),
					"intent_score": item.get("intent_score"),
				}
				for item in score_history
			],
			"interaction_history": [
				{"interaction_date": item.get("interaction_datetime"), "channel": item.get("channel"),
				 "direction": item.get("direction"), "outcome": item.get("outcome"),
				 "source_verified": item.get("source_verified")}
				for item in interactions
			],
			"applications": applications,
			"guardian_signals": guardians,
			"lifecycle_history": lifecycle,
		},
		"unknowns": [
			key for key, value in row.items()
			if key in {"assessment_status", "interest_level", "fit_level", "primary_barrier", "latest_score"}
			and value in (None, "")
		],
		"provenance_ids": [f"student:{student}"],
	}
	return {"student_360": student_360, "signals": student_360, "decision_context": decision_context}


def service_evidence(run_type: str, run_id: str, stage_kind: str, stage_generation: int, lease_token: str) -> dict[str, Any]:
	"""Return only current, minimized service evidence.  It is never persisted in crm-agents."""
	_service_only()
	run = frappe.get_doc(run_type, run_id)
	stage = frappe.get_doc("CRM Analysis Run Stage", {"parent_run_type": run_type, "parent_run": run_id, "stage_kind": stage_kind})
	if stage.status in TERMINAL:
		return {"terminal": True, "status": stage.status}
	if (
		stage.status != "running"
		or int(stage.stage_generation or 0) != int(stage_generation)
		or stage.get("lease_token") != str(lease_token or "")
		or not stage.get("lease_expires_at")
		or stage.lease_expires_at <= _lease_now()
	):
		frappe.throw("Evidence request does not own the current stage lease.", frappe.PermissionError)
	domain = "student" if run_type == RUN_TYPES["student"] else "school"
	target = run.student if domain == "student" else run.high_school
	revision, digest = _source(domain, target, run.get("admission_year"))
	if revision != str(stage.expected_source_revision) or digest != stage.expected_source_digest:
		frappe.db.sql(
			"UPDATE `tabCRM Analysis Run Stage` SET status='abstained', claims='[]', terminal_reason='superseded', lease_token=NULL, lease_expires_at=NULL "
			"WHERE name=%s AND status='running' AND stage_generation=%s AND lease_token=%s",
			(stage.name, int(stage_generation), str(lease_token)),
		)
		run.db_set("status", _parent_status(run_type, run_id), update_modified=False)
		return {"terminal": True, "status": "abstained", "reason": "superseded"}
	evidence = (
		_student_stage_evidence(target, revision)
		if domain == "student"
		else {"school": get_school_intelligence(target, str(run.get("admission_year") or "") or None)}
	)
	return {"run_id": run_id, "stage_kind": stage_kind, "source_revision": revision, "source_digest": digest, "target": target, "evidence": evidence}


def execution(run_type: str, run_id: str) -> dict[str, Any]:
	"""Materialize a generic outbox signal into bounded stage work.

	This service-only command intentionally returns no requester, target name or
	evidence.  The worker uses the returned stage identity to claim durable work
	and fetches minimized evidence only when it executes that stage.
	"""
	_service_only()
	if run_type not in RUN_TYPES.values():
		frappe.throw("Invalid Intelligence Run type.", frappe.ValidationError)
	run = frappe.get_doc(run_type, run_id)
	stages = frappe.get_all(
		"CRM Analysis Run Stage",
		filters={"parent_run_type": run_type, "parent_run": run_id, "status": ["in", ["queued", "running"]]},
		fields=["stage_kind", "stage_key", "stage_generation", "expected_source_revision", "expected_source_digest"],
		order_by="creation asc",
	)
	return {
		"run_kind": "student" if run_type == RUN_TYPES["student"] else "school",
		"run_id": run.name,
		"source_revision": str(run.source_revision),
		"source_digest": run.source_digest,
		"trigger": run.trigger,
		"admission_decision": run.get("admission_decision"),
		"admission_event": run.get("admission_event"),
		"candidate_revision": str(run.get("candidate_revision") or run.source_revision),
		"policy_revision": run.get("policy_revision"),
		"stages": [
			{
				"stage_kind": stage.stage_kind,
				"stage_key": stage.stage_key,
				"stage_generation": int(stage.stage_generation or 0),
				"expected_source_revision": str(stage.expected_source_revision),
				"expected_source_digest": stage.expected_source_digest,
			}
			for stage in stages
		],
	}


def claim_stage(*, run_type: str, run_id: str, stage_kind: str, stage_generation: int) -> dict[str, Any]:
	"""Acquire the sole execution lease for a stage.

	The outbox is at-least-once.  A worker must claim before it requests model
	evidence, so duplicate delivery cannot create duplicate NBA execution.  An
	expired lease may be recovered, but increments the generation and therefore
	fences every stale worker and settlement.
	"""
	_service_only()
	if run_type not in RUN_TYPES.values() or stage_kind not in _stage_kinds_for(run_type):
		frappe.throw("Invalid Analysis Run stage identity.", frappe.ValidationError)
	stage = frappe.get_doc("CRM Analysis Run Stage", {"parent_run_type": run_type, "parent_run": run_id, "stage_kind": stage_kind})
	frappe.db.sql("SELECT name FROM `tabCRM Analysis Run Stage` WHERE name=%s FOR UPDATE", (stage.name,))
	stage = frappe.get_doc("CRM Analysis Run Stage", stage.name)
	if stage.status in TERMINAL:
		return {"terminal": True, "status": stage.status, "stage_generation": int(stage.stage_generation or 0)}
	# ``stage_generation`` in crm-agents' durable outbox is the generation
	# observed when Frappe materialized the stage.  A retry may legitimately
	# carry an older hint after a lease was claimed/reclaimed; the live Frappe
	# row and returned lease token are the authority.  Future generations cannot
	# be claimed before Frappe has created them.
	if int(stage_generation) > int(stage.stage_generation or 0):
		frappe.throw("Stage claim references a future generation.", frappe.ValidationError)
	now = _lease_now()
	if stage.status == "running" and stage.get("lease_expires_at") and stage.lease_expires_at > now:
		return {"claimed": False, "deferred": True, "status": "running", "stage_generation": int(stage.stage_generation or 0), "retry_after": str(stage.lease_expires_at)}
	# Recovery also advances generation.  The first claim advances 0 -> 1 so a
	# worker can never settle with a generation copied from the outbox payload.
	generation = int(stage.stage_generation or 0) + 1
	token = frappe.generate_hash(length=48)
	# Do not use Frappe's add_to_date here: it applies the site timezone to a
	# naive value and shifts a UTC database lease by the local offset.
	lease_until = now + timedelta(minutes=int(frappe.conf.get("crm_intelligence_stage_lease_minutes", 10) or 10))
	frappe.db.sql(
		"UPDATE `tabCRM Analysis Run Stage` SET status='running', stage_generation=%s, lease_token=%s, lease_expires_at=%s "
		"WHERE name=%s AND stage_generation=%s AND (status='queued' OR (status='running' AND (lease_expires_at IS NULL OR lease_expires_at <= %s)))",
		(generation, token, lease_until, stage.name, int(stage.stage_generation or 0), now),
	)
	if frappe.db.sql("SELECT ROW_COUNT() AS affected", as_dict=True)[0].affected != 1:
		frappe.throw("Stage claim lost its compare-and-swap fence.", frappe.ValidationError)
	run = frappe.get_doc(run_type, run_id)
	run.db_set("status", "running", update_modified=False)
	return {
		"claimed": True, "run_id": run_id, "run_kind": "student" if run_type == RUN_TYPES["student"] else "school",
		"stage_kind": stage_kind, "stage_key": stage.stage_key, "stage_generation": generation,
		"lease_token": token, "lease_expires_at": str(lease_until),
		"expected_source_revision": str(stage.expected_source_revision), "expected_source_digest": stage.expected_source_digest,
	}


def _stage_kinds_for(run_type: str) -> set[str]:
	return set(STAGES["student" if run_type == RUN_TYPES["student"] else "school"])


def authorize_next_best_action_write(*, run_id: str, stage_generation: int, lease_token: str, expected_source_revision: str, expected_source_digest: str) -> dict[str, str]:
	"""Fence the sole NBA writer against an actively leased Student Run stage.

	This command is intentionally called by the CRM Action command immediately
	before its Student row CAS.  A stage key alone is never authority: an old
	worker must present the parent run, current lease generation/token and the
	authoritative source identity it analysed.
	"""
	_service_only()
	run_type = RUN_TYPES["student"]
	stage = frappe.get_doc("CRM Analysis Run Stage", {
		"parent_run_type": run_type, "parent_run": run_id, "stage_kind": "next_best_action",
	})
	frappe.db.sql("SELECT name FROM `tabCRM Analysis Run Stage` WHERE name=%s FOR UPDATE", (stage.name,))
	stage = frappe.get_doc("CRM Analysis Run Stage", stage.name)
	if (
		stage.status != "running"
		or int(stage.stage_generation or 0) != int(stage_generation)
		or stage.get("lease_token") != str(lease_token or "")
		or not stage.get("lease_expires_at") or stage.lease_expires_at <= _lease_now()
		or str(stage.expected_source_revision) != str(expected_source_revision)
		or stage.expected_source_digest != expected_source_digest
	):
		frappe.throw("Next Best Action write does not own the current Intelligence Run stage lease.", frappe.PermissionError)
	# Defense in depth over the claim-time dependency guard: an NBA result may
	# only be written once its sibling 360 stage has actually completed.
	sibling_status = frappe.db.get_value(
		"CRM Analysis Run Stage",
		{"parent_run_type": run_type, "parent_run": run_id, "stage_kind": "student_360"},
		"status",
	)
	if sibling_status != "completed":
		frappe.throw(
			"Next Best Action write requires a completed sibling Student 360 stage.",
			frappe.PermissionError,
		)
	run = frappe.get_doc(run_type, run_id)
	current_revision, current_digest = _source("student", run.student)
	if current_revision != str(expected_source_revision) or current_digest != expected_source_digest:
		frappe.throw("Next Best Action source is superseded.", frappe.ValidationError)
	return {
		"student": run.student,
		"source_revision": current_revision,
		"source_digest": current_digest,
		"stage_key": stage.stage_key,
		"run_id": run.name,
	}


def settle_stage(*, run_type: str, run_id: str, stage_kind: str, stage_generation: int, lease_token: str, expected_source_revision: str, expected_source_digest: str, status: str, claims=None, terminal_reason: str | None = None, policy_revision: str | None = None, model_revision: str | None = None, result_digest: str | None = None, completed_metadata: dict | None = None, report=None) -> dict[str, Any]:
	_service_only()
	if status not in TERMINAL:
		frappe.throw("Only terminal stage settlement is allowed.", frappe.ValidationError)
	result_digest = _validated_result_digest(result_digest)
	report_json = json.dumps(report or {}, ensure_ascii=False, separators=(",", ":")) if report else None
	terminal_reason = str(terminal_reason).strip() if terminal_reason is not None else None
	if terminal_reason is not None and len(terminal_reason) > 500:
		frappe.throw("Analysis Run terminal reason is bounded.", frappe.ValidationError)
	if status in {"failed", "dead_lettered"} and not terminal_reason:
		frappe.throw("Failed or dead-lettered stages require a terminal reason.", frappe.ValidationError)
	validate_claim_set(claims)
	if completed_metadata not in (None, {}):
		frappe.throw("Completion metadata is not part of the Intelligence Run contract.", frappe.ValidationError)
	validate_execution_revisions(policy_revision, model_revision, required=status == "completed")
	if any(claim.get("visibility") != "shareable" for claim in (claims or [])):
		frappe.throw("Only shareable claims may be persisted on an Analysis Run stage.", frappe.PermissionError)
	stage = frappe.get_doc("CRM Analysis Run Stage", {"parent_run_type": run_type, "parent_run": run_id, "stage_kind": stage_kind})
	# Terminal replay is safe only when it repeats exactly the persisted result.
	if stage.status in TERMINAL:
		stored_claims = frappe.parse_json(stage.claims) if stage.claims else []
		if stage.status == status and stored_claims == (claims or []) and (stage.terminal_reason or None) == (terminal_reason or None) and (stage.policy_revision or None) == (policy_revision or None) and (stage.model_revision or None) == (model_revision or None) and (stage.get("result_digest") or None) == (result_digest or None):
			return {"run_id": run_id, "stage_kind": stage_kind, "status": stage.status, "parent_status": frappe.db.get_value(run_type, run_id, "status"), "policy_revision": stage.policy_revision, "model_revision": stage.model_revision, "result_digest": stage.get("result_digest"), "replayed": True}
		frappe.throw("Stage already has a different terminal settlement.", frappe.ValidationError)
	if (int(stage.stage_generation or 0) != int(stage_generation) or stage.get("lease_token") != str(lease_token or "")
		or stage.expected_source_revision != str(expected_source_revision) or stage.expected_source_digest != expected_source_digest):
		frappe.throw("Stage fence mismatch.", frappe.ValidationError)
	run = frappe.get_doc(run_type, run_id)
	domain = "student" if run_type == RUN_TYPES["student"] else "school"
	target = run.student if domain == "student" else run.high_school
	current_revision, current_digest = _source(domain, target, run.get("admission_year"))
	if current_revision != str(expected_source_revision) or current_digest != expected_source_digest:
		status, terminal_reason, claims, policy_revision, model_revision, result_digest = "abstained", "superseded", [], None, None, None
	frappe.db.sql(
		"UPDATE `tabCRM Analysis Run Stage` SET status=%s, claims=%s, report_json=%s, terminal_reason=%s, policy_revision=%s, model_revision=%s, result_digest=%s, lease_token=NULL, lease_expires_at=NULL "
		"WHERE name=%s AND status IN ('queued', 'running') AND stage_generation=%s "
		"AND lease_token=%s AND expected_source_revision=%s AND expected_source_digest=%s",
		(status, json.dumps(claims or []), report_json, terminal_reason, policy_revision, model_revision, result_digest, stage.name, int(stage_generation), str(lease_token or ""), str(expected_source_revision), expected_source_digest),
	)
	if frappe.db.sql("SELECT ROW_COUNT() AS affected", as_dict=True)[0].affected != 1:
		frappe.throw("Stage settlement lost its compare-and-swap fence.", frappe.ValidationError)
	parent_status = _parent_status(run_type, run_id)
	run.db_set("status", parent_status, update_modified=False)
	if parent_status in TERMINAL:
		run.db_set("terminal_reason", terminal_reason if parent_status != "completed" else None, update_modified=False)
	return {"run_id": run_id, "stage_kind": stage_kind, "status": status, "parent_status": parent_status, "policy_revision": policy_revision, "model_revision": model_revision, "result_digest": result_digest}


def _validated_result_digest(result_digest: str | None) -> str | None:
	"""Accept an optional lowercase 64-hex content digest for the stage result."""
	if result_digest in (None, ""):
		return None
	result_digest = str(result_digest).strip().lower()
	if not re.fullmatch(r"[a-f0-9]{64}", result_digest):
		frappe.throw("Analysis Run result digest must be a 64-character hex string.", frappe.ValidationError)
	return result_digest
