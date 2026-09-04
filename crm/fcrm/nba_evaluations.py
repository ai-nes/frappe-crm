"""Frappe authority for the durable, standalone NBA Evaluation runtime.

This is a sibling of ``crm.fcrm.intelligence_runs`` -- it reuses the same
outbox / lease / compare-and-swap patterns -- but a ``CRM NBA Evaluation`` is
not a stage of any Student Analysis Run and nothing about Student 360 status
gates it. The agent service receives an identity-only outbox signal, claims a
fenced lease, re-reads the authoritative evaluation input from Frappe, and
settles a terminal result. Run status is separate from business disposition.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import frappe
from frappe.utils import add_to_date, now_datetime

from crm.api.nba_evaluation import build_nba_evaluation_input
from crm.fcrm.intelligence_runs import _lease_now, _require_force_rerun_permission, _service_only

DOCTYPE = "CRM NBA Evaluation"
TERMINAL = {"completed", "failed", "dead_lettered"}
ACTIVE = {"queued", "running"}
_ENGINE_REVISION_DEFAULT = "nba-engine-v0"
_IDENTITY_DIGEST_FIELDS = (
	"context_digest",
	"eligible_set_digest",
	"library_digest",
	"decision_digest",
	"eligibility_digest",
	"timing_digest",
)


# --------------------------------------------------------------------------- #
# Feature gate
# --------------------------------------------------------------------------- #
def nba_evaluation_runtime_enabled() -> bool:
	return frappe.conf.get("crm_nba_evaluation_runtime_enabled", 0) in (1, "1", True)


def require_nba_evaluation_runtime_enabled() -> None:
	if not nba_evaluation_runtime_enabled():
		frappe.throw("NBA Evaluation runtime is not enabled.", frappe.ValidationError)


# --------------------------------------------------------------------------- #
# Pure helpers (no Frappe access -- exercised without a bench)
# --------------------------------------------------------------------------- #
def _identity_from_envelope(envelope: dict) -> dict[str, Any]:
	"""Project the bound identity of an NBA Evaluation v1 input envelope."""
	student = envelope["student"]
	policies = envelope["policies"]
	eligible = envelope["eligible_action_set"]
	return {
		"evaluation_key": envelope["evaluation_key"],
		"context_revision": str(student["context_revision"]),
		"context_digest": student["context_digest"],
		"eligible_set_revision": str(eligible["set_revision"]),
		"eligible_set_digest": eligible["set_digest"],
		"library_digest": policies["library_digest"],
		"decision_policy_revision": policies["decision_revision"],
		"decision_digest": policies["decision_digest"],
		"eligibility_digest": policies["eligibility_digest"],
		"timing_digest": policies["timing_digest"],
		"evaluation_clock": envelope["evaluation_clock"],
	}


def _bounded_hex64(value: object, label: str) -> str | None:
	if value in (None, ""):
		return None
	text = str(value).strip().lower()
	if not re.fullmatch(r"[a-f0-9]{64}", text):
		raise ValueError(f"NBA Evaluation {label} must be a 64-character hex string.")
	return text


# --------------------------------------------------------------------------- #
# Frappe-facing helpers
# --------------------------------------------------------------------------- #
def _engine_revision() -> str:
	return str(frappe.conf.get("crm_nba_engine_revision") or _ENGINE_REVISION_DEFAULT)


def _lease_minutes() -> int:
	return max(1, int(frappe.conf.get("crm_nba_evaluation_lease_minutes", 10) or 10))


def _manual_quota() -> tuple[int, int]:
	return (
		max(1, int(frappe.conf.get("crm_nba_manual_requests_per_actor_target", 3) or 3)),
		max(1, int(frappe.conf.get("crm_nba_manual_request_window_minutes", 60) or 60)),
	)


def _validated_hex64(value: object, label: str) -> str | None:
	try:
		return _bounded_hex64(value, label)
	except ValueError as exc:
		frappe.throw(str(exc), frappe.ValidationError)


def _require_student_scope(student: str) -> None:
	if not student or not frappe.db.exists("CRM Student", student):
		frappe.throw("NBA Evaluation target does not exist.", frappe.DoesNotExistError)
	if not frappe.has_permission("CRM Student", "read", student):
		frappe.throw("NBA Evaluation target is outside current scope.", frappe.PermissionError)


def _request_clock():
	"""Quantise the request moment to the minute.

	``build_nba_evaluation_input`` folds the wall clock into the feasible timing
	domain, so an unquantised clock would make the bound ``evaluation_key`` drift
	every second and defeat dedup. Quantising collapses double-clicks and retries
	within a minute onto one identity while a later re-request still earns a fresh
	run over unchanged governed inputs.
	"""
	return now_datetime().replace(second=0, microsecond=0)


def _identity_for(student: str, clock) -> tuple[dict, dict[str, Any]]:
	"""Build the evaluation input and its bound identity at a fixed clock."""
	envelope = build_nba_evaluation_input(student, now=clock)
	return envelope, _identity_from_envelope(envelope)


def _stored_identity(doc) -> tuple[dict, dict[str, Any]]:
	"""Recompute the live identity at the run's own recorded evaluation clock."""
	return _identity_for(doc.student, frappe.utils.get_datetime(doc.evaluation_clock))


def _is_superseded(doc, identity: dict[str, Any]) -> bool:
	if identity["evaluation_key"] != doc.evaluation_key:
		return True
	return any(str(identity[field] or "") != str(doc.get(field) or "") for field in _IDENTITY_DIGEST_FIELDS)


def _mark_superseded(name: str) -> None:
	frappe.db.sql(
		"UPDATE `tabCRM NBA Evaluation` SET status='failed', terminal_reason='superseded', "
		"disposition=NULL, lease_token=NULL, lease_expires_at=NULL "
		"WHERE name=%s AND status IN ('queued', 'running')",
		(name,),
	)


def _receipt(name: str) -> dict[str, Any]:
	doc = frappe.get_doc(DOCTYPE, name)
	return {
		"evaluation": doc.name,
		"student": doc.student,
		"status": doc.status,
		"disposition": doc.disposition,
		"contract_version": doc.contract_version,
		"engine_revision": doc.engine_revision,
		"evaluation_key": doc.evaluation_key,
		"run_generation": int(doc.run_generation or 0),
		"recommendation_count": int(doc.recommendation_count or 0),
		"terminal_reason": doc.terminal_reason,
	}


def _enforce_manual_quota(student: str) -> None:
	limit, window_minutes = _manual_quota()
	window_start = add_to_date(now_datetime(), minutes=-window_minutes)
	count = frappe.db.count(
		DOCTYPE,
		filters={
			"student": student,
			"trigger": "manual",
			"requested_by": frappe.session.user,
			"creation": [">=", window_start],
		},
	)
	if count >= limit:
		frappe.throw(
			"Manual NBA Evaluation limit reached for this student; try again later.", frappe.ValidationError
		)


def _single_active(student: str, evaluation_key: str):
	# The caller already holds the Student-row ``FOR UPDATE`` mutex, and that
	# locking read is this transaction's first statement, so the REPEATABLE READ
	# snapshot is pinned after any racing request committed: a plain read here
	# already sees the latest-committed active run.
	names = frappe.get_all(
		DOCTYPE,
		filters={"student": student, "evaluation_key": evaluation_key, "status": ["in", sorted(ACTIVE)]},
		pluck="name",
		order_by="creation asc",
		limit_page_length=2,
	)
	if len(names) > 1:
		frappe.throw(
			"NBA Evaluation active-run invariant is violated; operator repair is required.",
			frappe.ValidationError,
		)
	return frappe.get_doc(DOCTYPE, names[0]) if names else None


def _latest_terminal(student: str, evaluation_key: str):
	names = frappe.get_all(
		DOCTYPE,
		filters={"student": student, "evaluation_key": evaluation_key, "status": ["in", sorted(TERMINAL)]},
		pluck="name",
		order_by="creation desc",
		limit_page_length=1,
	)
	return frappe.get_doc(DOCTYPE, names[0]) if names else None


def _insert_evaluation(
	student: str, identity: dict[str, Any], clock, key: str | None, *, trigger: str = "manual"
):
	values = {
		"doctype": DOCTYPE,
		"student": student,
		"trigger": trigger,
		"status": "queued",
		"run_generation": 0,
		"contract_version": "nba-evaluation-v1",
		"engine_revision": _engine_revision(),
		"evaluation_key": identity["evaluation_key"],
		"context_revision": identity["context_revision"],
		"context_digest": identity["context_digest"],
		"eligible_set_revision": identity["eligible_set_revision"],
		"eligible_set_digest": identity["eligible_set_digest"],
		"library_digest": identity["library_digest"],
		"decision_policy_revision": identity["decision_policy_revision"],
		"decision_digest": identity["decision_digest"],
		"eligibility_digest": identity["eligibility_digest"],
		"timing_digest": identity["timing_digest"],
		"evaluation_clock": clock,
	}
	if trigger == "manual":
		values["requested_by"] = frappe.session.user
		if key:
			values["request_idempotency_key"] = key
	return frappe.get_doc(values).insert(ignore_permissions=True)


# --------------------------------------------------------------------------- #
# Lifecycle commands
# --------------------------------------------------------------------------- #
def request_nba_evaluation(
	*, student: str, idempotency_key: str | None, force_reason: str | None = None
) -> dict[str, Any]:
	"""Create or reuse one scoped NBA Evaluation run; no caller credential is persisted.

	Delegated users may call this (it is not service-only), but the caller must
	be able to read the Student and stays under a bounded manual quota.
	"""
	require_nba_evaluation_runtime_enabled()
	_require_student_scope(student)
	key = str(idempotency_key or "").strip()
	if not key or len(key) > 140:
		frappe.throw("Idempotency-Key is required and bounded to 140 characters.", frappe.ValidationError)
	# The Student row is the mutex for button-click races on one identity.
	frappe.db.sql("SELECT name FROM `tabCRM Student` WHERE name=%s FOR UPDATE", (student,))
	clock = _request_clock()
	_, identity = _identity_for(student, clock)
	evaluation_key = identity["evaluation_key"]

	existing_key = frappe.db.get_value(
		DOCTYPE, {"request_idempotency_key": key}, ["name", "requested_by", "student"], as_dict=True
	)
	if existing_key:
		if existing_key.requested_by and existing_key.requested_by != frappe.session.user:
			frappe.throw("Idempotency-Key belongs to another requester.", frappe.PermissionError)
		if existing_key.student != student:
			frappe.throw(
				"Idempotency-Key was already used for a different student.",
				frappe.ValidationError,
			)
		return _receipt(existing_key.name)

	force_reason = _require_force_rerun_permission(force_reason)
	active = _single_active(student, evaluation_key)
	if active:
		return _receipt(active.name)
	if not force_reason:
		terminal = _latest_terminal(student, evaluation_key)
		if terminal:
			return _receipt(terminal.name)
	_enforce_manual_quota(student)
	try:
		evaluation = _insert_evaluation(student, identity, clock, key)
	except frappe.exceptions.DuplicateEntryError:
		# A concurrent request with the same Idempotency-Key won the insert race
		# after both passed the lookup above. Return its receipt rather than a 500.
		existing = frappe.db.get_value(DOCTYPE, {"request_idempotency_key": key}, "name")
		if not existing:
			raise
		return _receipt(existing)
	from crm.api.agent_events import record_nba_evaluation_event

	record_nba_evaluation_event(evaluation)
	return _receipt(evaluation.name)


def execution(evaluation: str) -> dict[str, Any]:
	"""Materialize the identity-only outbox signal into bounded run identity.

	Service-only. Returns no requester, no Student name beyond the link, and no
	evaluation input -- the worker claims first, then reads the snapshot.
	"""
	require_nba_evaluation_runtime_enabled()
	_service_only()
	doc = frappe.get_doc(DOCTYPE, evaluation)
	return {
		"evaluation": doc.name,
		"student": doc.student,
		"status": doc.status,
		"contract_version": doc.contract_version,
		"engine_revision": doc.engine_revision,
		"evaluation_key": doc.evaluation_key,
		"run_generation": int(doc.run_generation or 0),
		"context_revision": doc.context_revision,
		"context_digest": doc.context_digest,
		"eligible_set_revision": doc.eligible_set_revision,
		"eligible_set_digest": doc.eligible_set_digest,
		"library_digest": doc.library_digest,
		"decision_policy_revision": doc.decision_policy_revision,
		"decision_digest": doc.decision_digest,
		"eligibility_digest": doc.eligibility_digest,
		"timing_digest": doc.timing_digest,
		"evaluation_clock": str(doc.evaluation_clock) if doc.evaluation_clock else None,
	}


def claim_nba_evaluation(*, evaluation: str, run_generation: int) -> dict[str, Any]:
	"""Acquire the sole execution lease for one evaluation run.

	The outbox is at-least-once; a worker must claim before it reads the
	snapshot, so duplicate delivery cannot create duplicate evaluation. An
	expired lease may be recovered, but that increments the generation and so
	fences every stale worker and settlement.
	"""
	require_nba_evaluation_runtime_enabled()
	_service_only()
	doc = frappe.get_doc(DOCTYPE, evaluation)
	frappe.db.sql("SELECT name FROM `tabCRM NBA Evaluation` WHERE name=%s FOR UPDATE", (doc.name,))
	doc.reload()
	if doc.status in TERMINAL:
		return {"terminal": True, "status": doc.status, "run_generation": int(doc.run_generation or 0)}
	if int(run_generation) > int(doc.run_generation or 0):
		frappe.throw("Evaluation claim references a future generation.", frappe.ValidationError)

	_, identity = _stored_identity(doc)
	if _is_superseded(doc, identity):
		_mark_superseded(doc.name)
		return {"terminal": True, "status": "failed", "reason": "superseded"}

	now = _lease_now()
	if doc.status == "running" and doc.get("lease_expires_at") and doc.lease_expires_at > now:
		return {
			"claimed": False,
			"deferred": True,
			"status": "running",
			"run_generation": int(doc.run_generation or 0),
			"retry_after": str(doc.lease_expires_at),
		}
	generation = int(doc.run_generation or 0) + 1
	token = frappe.generate_hash(length=48)
	lease_until = now + timedelta(minutes=_lease_minutes())
	frappe.db.sql(
		"UPDATE `tabCRM NBA Evaluation` SET status='running', run_generation=%s, lease_token=%s, lease_expires_at=%s "
		"WHERE name=%s AND run_generation=%s AND (status='queued' OR (status='running' AND (lease_expires_at IS NULL OR lease_expires_at <= %s)))",
		(generation, token, lease_until, doc.name, int(doc.run_generation or 0), now),
	)
	if frappe.db.sql("SELECT ROW_COUNT() AS affected", as_dict=True)[0].affected != 1:
		frappe.throw("Evaluation claim lost its compare-and-swap fence.", frappe.ValidationError)
	return {
		"claimed": True,
		"evaluation": doc.name,
		"student": doc.student,
		"run_generation": generation,
		"lease_token": token,
		"lease_expires_at": str(lease_until),
		"contract_version": doc.contract_version,
		"engine_revision": doc.engine_revision,
		"evaluation_key": doc.evaluation_key,
	}


def snapshot(*, evaluation: str, lease_token: str) -> dict[str, Any]:
	"""Return the current authoritative evaluation input under an owned lease."""
	require_nba_evaluation_runtime_enabled()
	_service_only()
	doc = frappe.get_doc(DOCTYPE, evaluation)
	if doc.status in TERMINAL:
		return {"terminal": True, "status": doc.status}
	if (
		doc.status != "running"
		or doc.get("lease_token") != str(lease_token or "")
		or not doc.get("lease_expires_at")
		or doc.lease_expires_at <= _lease_now()
	):
		frappe.throw("Snapshot request does not own the current evaluation lease.", frappe.PermissionError)
	envelope, identity = _stored_identity(doc)
	if _is_superseded(doc, identity):
		frappe.db.sql(
			"UPDATE `tabCRM NBA Evaluation` SET status='failed', terminal_reason='superseded', "
			"disposition=NULL, lease_token=NULL, lease_expires_at=NULL "
			"WHERE name=%s AND status='running' AND lease_token=%s",
			(doc.name, str(lease_token or "")),
		)
		return {"terminal": True, "status": "failed", "reason": "superseded"}
	return {
		"evaluation": doc.name,
		"student": doc.student,
		"run_generation": int(doc.run_generation or 0),
		"lease_token": doc.lease_token,
		"contract_version": doc.contract_version,
		"engine_revision": doc.engine_revision,
		"evaluation_key": doc.evaluation_key,
		"input": envelope,
		"input_digest": _canonical_input_digest(envelope),
	}


def _canonical_input_digest(envelope: dict) -> str:
	from crm.fcrm.nba_evaluation_input import input_digest

	return input_digest(envelope)


def settle_nba_evaluation(
	*,
	evaluation: str,
	run_generation: int,
	lease_token: str,
	status: str,
	disposition: str | None = None,
	result_digest: str | None = None,
	trace_digest: str | None = None,
	terminal_reason: str | None = None,
	engine_revision_settled: str | None = None,
	recommendation_count: int = 0,
) -> dict[str, Any]:
	"""Terminal-only, fenced worker settlement with idempotent terminal replay."""
	require_nba_evaluation_runtime_enabled()
	_service_only()
	if status not in TERMINAL:
		frappe.throw("Only terminal NBA Evaluation settlement is allowed.", frappe.ValidationError)
	result_digest = _validated_hex64(result_digest, "result digest")
	trace_digest = _validated_hex64(trace_digest, "trace digest")
	disposition = str(disposition).strip() if disposition not in (None, "") else None
	if disposition is not None and len(disposition) > 64:
		frappe.throw("NBA Evaluation disposition is bounded to 64 characters.", frappe.ValidationError)
	terminal_reason = str(terminal_reason).strip() if terminal_reason is not None else None
	if terminal_reason is not None and len(terminal_reason) > 500:
		frappe.throw("NBA Evaluation terminal reason is bounded to 500 characters.", frappe.ValidationError)
	if status in {"failed", "dead_lettered"} and not terminal_reason:
		frappe.throw("Failed or dead-lettered evaluations require a terminal reason.", frappe.ValidationError)
	recommendation_count = int(recommendation_count or 0)
	if recommendation_count < 0:
		frappe.throw("NBA Evaluation recommendation count cannot be negative.", frappe.ValidationError)
	engine_revision_settled = (
		str(engine_revision_settled).strip() if engine_revision_settled not in (None, "") else None
	)

	doc = frappe.get_doc(DOCTYPE, evaluation)
	if doc.status in TERMINAL:
		same = (
			doc.status == status
			and (doc.disposition or None) == (disposition or None)
			and (doc.terminal_reason or None) == (terminal_reason or None)
			and (doc.get("result_digest") or None) == (result_digest or None)
			and (doc.get("trace_digest") or None) == (trace_digest or None)
			and int(doc.recommendation_count or 0) == recommendation_count
			and (doc.get("engine_revision_settled") or None) == (engine_revision_settled or None)
		)
		if same:
			return {
				"evaluation": doc.name,
				"student": doc.student,
				"status": doc.status,
				"disposition": doc.disposition,
				"result_digest": doc.get("result_digest"),
				"trace_digest": doc.get("trace_digest"),
				"recommendation_count": int(doc.recommendation_count or 0),
				"engine_revision_settled": doc.get("engine_revision_settled"),
				"replayed": True,
			}
		frappe.throw("Evaluation already has a different terminal settlement.", frappe.ValidationError)

	if int(doc.run_generation or 0) != int(run_generation) or doc.get("lease_token") != str(
		lease_token or ""
	):
		frappe.throw("Evaluation settlement fence mismatch.", frappe.ValidationError)

	_, identity = _stored_identity(doc)
	if _is_superseded(doc, identity):
		status, disposition, terminal_reason = "failed", None, "superseded"
		result_digest = trace_digest = engine_revision_settled = None
		recommendation_count = 0

	frappe.db.sql(
		"UPDATE `tabCRM NBA Evaluation` SET status=%s, disposition=%s, terminal_reason=%s, result_digest=%s, "
		"trace_digest=%s, recommendation_count=%s, engine_revision_settled=%s, lease_token=NULL, lease_expires_at=NULL "
		"WHERE name=%s AND status IN ('queued', 'running') AND run_generation=%s AND lease_token=%s",
		(
			status,
			disposition,
			terminal_reason,
			result_digest,
			trace_digest,
			recommendation_count,
			engine_revision_settled,
			doc.name,
			int(run_generation),
			str(lease_token or ""),
		),
	)
	if frappe.db.sql("SELECT ROW_COUNT() AS affected", as_dict=True)[0].affected != 1:
		frappe.throw("Evaluation settlement lost its compare-and-swap fence.", frappe.ValidationError)
	return {
		"evaluation": doc.name,
		"student": doc.student,
		"status": status,
		"disposition": disposition,
		"result_digest": result_digest,
		"trace_digest": trace_digest,
		"recommendation_count": recommendation_count,
		"engine_revision_settled": engine_revision_settled,
	}


_COMMIT_DISPOSITIONS = {"RECOMMEND", "WAIT", "NO_ACTION", "ABSTAIN"}
_MAX_COMMIT_RECOMMENDATIONS = 10
_RANK_PRIORITY = {1: "high", 2: "medium"}


def _as_list(value: object) -> list:
	if value in (None, ""):
		return []
	if isinstance(value, str):
		value = frappe.parse_json(value)
	if isinstance(value, dict):
		return [value]
	return list(value or [])


def _resolve_committed_action(action_ref: dict) -> str | None:
	"""Map a wire ``ACT-<CODE>`` action id back to its ``CRM Action`` row, if any."""
	action_id = str((action_ref or {}).get("action_id") or "").strip()
	if not action_id:
		return None
	code = action_id[4:] if action_id.startswith("ACT-") else action_id
	return frappe.db.get_value("CRM Action", {"code": code}, "name") or frappe.db.get_value(
		"CRM Action", code, "name"
	)


def _committed_recommendation_reason(rec: dict) -> str:
	facts = [str(fact).strip() for fact in (rec.get("explanation_facts") or []) if str(fact).strip()]
	if facts:
		return " ".join(facts)[:2000]
	codes = [str(code).strip() for code in (rec.get("reason_codes") or []) if str(code).strip()]
	if codes:
		return ", ".join(codes)[:2000]
	return "NBA evaluation recommendation"


def _committed_recommendation_priority(rank: int) -> str:
	return _RANK_PRIORITY.get(int(rank), "low")


def _committed_datetime(value: object):
	"""Coerce an ISO-8601 instant (possibly tz-aware) to a naive DB datetime."""
	if value in (None, ""):
		return None
	parsed = frappe.utils.get_datetime(str(value))
	if parsed is None:
		return None
	return parsed.replace(tzinfo=None)


def _existing_recommendation_ids(evaluation: str) -> list[str]:
	return frappe.get_all(
		"CRM Recommendation",
		filters={"evaluation": evaluation},
		order_by="`rank` asc",
		pluck="name",
	)


def _terminal_commit_receipt(doc) -> dict[str, Any]:
	"""Replay receipt for an evaluation that already reached a terminal state."""
	if doc.status == "completed":
		return {
			"status": "accepted",
			"evaluation": doc.name,
			"recommendation_ids": _existing_recommendation_ids(doc.name),
			"result_digest": doc.get("result_digest"),
			"trace_digest": doc.get("trace_digest"),
		}
	return {
		"status": "superseded",
		"evaluation": doc.name,
		"recommendation_ids": [],
		"terminal_reason": doc.terminal_reason or "superseded",
	}


def _superseded_commit(name: str, run_generation: int, lease_token: str) -> dict[str, Any]:
	frappe.db.sql(
		"UPDATE `tabCRM NBA Evaluation` SET status='failed', terminal_reason='superseded', disposition=NULL, "
		"result_digest=NULL, trace_digest=NULL, evaluation_trace=NULL, engine_revision_settled=NULL, "
		"recommendation_count=0, revisit_at=NULL, reevaluation_trigger=NULL, "
		"lease_token=NULL, lease_expires_at=NULL "
		"WHERE name=%s AND status IN ('queued', 'running') AND run_generation=%s AND lease_token=%s",
		(name, int(run_generation), str(lease_token or "")),
	)
	if frappe.db.sql("SELECT ROW_COUNT() AS affected", as_dict=True)[0].affected != 1:
		frappe.throw("Evaluation commit lost its compare-and-swap fence.", frappe.ValidationError)
	return {
		"status": "superseded",
		"evaluation": name,
		"recommendation_ids": [],
		"terminal_reason": "superseded",
	}


def commit_nba_evaluation_result(
	*,
	evaluation: str,
	run_generation: int,
	lease_token: str,
	engine_revision: str | None = None,
	run_status: str = "completed",
	disposition: str | None = None,
	reason_codes: object = None,
	result_digest: str | None = None,
	trace_digest: str | None = None,
	revisit_at: str | None = None,
	reevaluation_trigger: str | None = None,
	recommendations: object = None,
	trace_entries: object = None,
	terminal_reason: str | None = None,
) -> dict[str, Any]:
	"""One fenced transaction that writes the terminal NBA Evaluation state plus
	its immutable ``CRM Recommendation`` rows.

	Used in place of :func:`settle_nba_evaluation` when the durable runtime flag
	is on. The row-level ``FOR UPDATE`` mutex is taken first, the live decision
	identity is recomputed for a supersede check, the terminal state is written
	under a compare-and-swap fence on ``run_generation`` + ``lease_token``, and
	0..N recommendation rows are inserted -- all or nothing. The path never
	creates a ``CRM Action Item``.
	"""
	require_nba_evaluation_runtime_enabled()
	_service_only()

	run_status = str(run_status or "completed").strip()
	if run_status not in {"completed", "failed"}:
		frappe.throw("NBA Evaluation commit accepts only a terminal run status.", frappe.ValidationError)
	recommendations = _as_list(recommendations)
	trace_entries = _as_list(trace_entries)
	terminal_reason = str(terminal_reason).strip() if terminal_reason not in (None, "") else None
	if terminal_reason is not None and len(terminal_reason) > 500:
		frappe.throw("NBA Evaluation terminal reason is bounded to 500 characters.", frappe.ValidationError)

	if run_status == "failed":
		if not terminal_reason:
			frappe.throw("A failed NBA Evaluation commit requires a terminal reason.", frappe.ValidationError)
		disposition = None
		result_digest = trace_digest = None
		recommendations = []
		trace_entries = []
		revisit_at = None
		reevaluation_trigger = None
	else:
		disposition = str(disposition).strip() if disposition not in (None, "") else None
		if disposition not in _COMMIT_DISPOSITIONS:
			frappe.throw("NBA Evaluation commit disposition is not recognised.", frappe.ValidationError)
		result_digest = _validated_hex64(result_digest, "result digest")
		trace_digest = _validated_hex64(trace_digest, "trace digest")
		if not result_digest or not trace_digest:
			frappe.throw("A completed NBA Evaluation commit requires both digests.", frappe.ValidationError)
		if len(recommendations) > _MAX_COMMIT_RECOMMENDATIONS:
			frappe.throw("NBA Evaluation commit exceeds the recommendation cap.", frappe.ValidationError)
		if disposition == "RECOMMEND" and not recommendations:
			frappe.throw("A RECOMMEND commit requires at least one recommendation.", frappe.ValidationError)
		if disposition != "RECOMMEND" and recommendations:
			frappe.throw(f"A {disposition} commit must not carry recommendations.", frappe.ValidationError)
		if disposition == "WAIT" and not (revisit_at or reevaluation_trigger):
			frappe.throw(
				"A WAIT commit requires a revisit_at or a reevaluation_trigger.", frappe.ValidationError
			)
		if disposition == "WAIT":
			revisit_at = _committed_datetime(revisit_at)
			reevaluation_trigger = (
				str(reevaluation_trigger).strip()[:140] if reevaluation_trigger not in (None, "") else None
			)
		else:
			revisit_at = None
			reevaluation_trigger = None
		ranks = sorted(int(rec.get("rank") or 0) for rec in recommendations)
		if ranks != list(range(1, len(recommendations) + 1)):
			frappe.throw("Recommendation ranks must be a dense 1-based sequence.", frappe.ValidationError)
		keys = [str(rec.get("recommendation_key") or "") for rec in recommendations]
		if "" in keys or len(set(keys)) != len(keys):
			frappe.throw("Every recommendation needs a unique recommendation key.", frappe.ValidationError)

	doc = frappe.get_doc(DOCTYPE, evaluation)
	if doc.status in TERMINAL:
		return _terminal_commit_receipt(doc)

	frappe.db.sql("SELECT name FROM `tabCRM NBA Evaluation` WHERE name=%s FOR UPDATE", (doc.name,))
	doc.reload()
	if doc.status in TERMINAL:
		return _terminal_commit_receipt(doc)

	if int(doc.run_generation or 0) != int(run_generation) or doc.get("lease_token") != str(
		lease_token or ""
	):
		frappe.throw("Evaluation commit fence mismatch.", frappe.ValidationError)

	_, identity = _stored_identity(doc)
	if _is_superseded(doc, identity):
		return _superseded_commit(doc.name, run_generation, lease_token)

	status = "completed" if run_status == "completed" else "failed"
	frappe.db.sql(
		"UPDATE `tabCRM NBA Evaluation` SET status=%s, disposition=%s, terminal_reason=%s, result_digest=%s, "
		"trace_digest=%s, evaluation_trace=%s, engine_revision_settled=%s, recommendation_count=%s, "
		"revisit_at=%s, reevaluation_trigger=%s, reevaluation_dispatched_at=NULL, "
		"lease_token=NULL, lease_expires_at=NULL "
		"WHERE name=%s AND status IN ('queued', 'running') AND run_generation=%s AND lease_token=%s",
		(
			status,
			disposition,
			terminal_reason,
			result_digest,
			trace_digest,
			frappe.as_json(trace_entries) if trace_entries else None,
			(engine_revision or doc.engine_revision or "").strip() or None,
			len(recommendations),
			revisit_at,
			reevaluation_trigger,
			doc.name,
			int(run_generation),
			str(lease_token or ""),
		),
	)
	if frappe.db.sql("SELECT ROW_COUNT() AS affected", as_dict=True)[0].affected != 1:
		frappe.throw("Evaluation commit lost its compare-and-swap fence.", frappe.ValidationError)

	recommendation_ids: list[str] = []
	for rec in sorted(recommendations, key=lambda item: int(item.get("rank") or 0)):
		rank = int(rec.get("rank") or 0)
		row = frappe.get_doc(
			{
				"doctype": "CRM Recommendation",
				"recommendation_id": f"{doc.name}-{rank}",
				"target_type": "CRM Student",
				"target_id": doc.student,
				"reason": _committed_recommendation_reason(rec),
				"priority": _committed_recommendation_priority(rank),
				"confidence": rec.get("confidence"),
				"recommended_at": now_datetime(),
				"expires_at": _committed_datetime(rec.get("expires_at")),
				"evaluation": doc.name,
				"ai_payload": rec,
				"recommendation_key": str(rec.get("recommendation_key") or ""),
				"rank": rank,
			}
		)
		action_name = _resolve_committed_action(rec.get("action_ref") or {})
		if action_name:
			row.action = action_name
		# The custom ``owner`` field (the assigned CRM Staff, unknown until a
		# Sales decision) shadows the framework ``owner`` column (the doc's
		# creator) and is stamped with the service session user on insert,
		# which is not a ``CRM Staff`` row; the ``action`` link is the only
		# meaningful link and is pre-resolved.
		row.flags.ignore_links = True
		row.insert(ignore_permissions=True)
		# Clear the framework-stamped session user back to unassigned via a
		# direct db write -- ``doc.owner = None`` + ``save()`` would still
		# trip Frappe's global set-only-once lock on any field named
		# ``owner`` (``frappe.model.meta.py: standard_set_once_fields``), and
		# leaving the stale value in place breaks both later link validation
		# and the Sales decision's own owner reassignment at Accept.
		frappe.db.set_value("CRM Recommendation", row.name, "owner", None, update_modified=False)
		recommendation_ids.append(row.name)

	return {
		"status": "accepted",
		"evaluation": doc.name,
		"recommendation_ids": recommendation_ids,
		"result_digest": result_digest,
		"trace_digest": trace_digest,
	}


# --------------------------------------------------------------------------- #
# Post-commit explanation (best effort, outside the commit fence)
# --------------------------------------------------------------------------- #
_RATIONALE_SOURCES = frozenset({"model", "fallback_absent"})
_EXPLANATION_STR_FIELDS = ("summary", "why_action", "why_now", "timing_reason", "uncertainty")
_EXPLANATION_LIST_FIELDS = ("evidence_summary", "execution_guidance")
_EXPLANATION_FIELDS = frozenset(_EXPLANATION_STR_FIELDS) | frozenset(_EXPLANATION_LIST_FIELDS)
_EXPLANATION_STR_MAX_CHARS = 500
_EXPLANATION_LIST_MAX_ITEMS = 8
_EXPLANATION_ITEM_MAX_CHARS = 400


def _validated_explanation(explanation: object) -> dict[str, Any]:
	"""Bounded structural validation of the grounded, structured explanation.

	The agent service is the one that grounds each field against the kernel's
	decision (action, timing, evidence); this validates only shape and bounds
	-- an unrecognised or missing field, an oversized string, or an oversized
	list is rejected before the write.
	"""
	if isinstance(explanation, str):
		try:
			explanation = frappe.parse_json(explanation)
		except Exception:
			frappe.throw("Explanation must be a JSON object.", frappe.ValidationError)
	if not isinstance(explanation, dict):
		frappe.throw("Explanation must be a JSON object.", frappe.ValidationError)

	unexpected = set(explanation) - _EXPLANATION_FIELDS
	if unexpected:
		frappe.throw("Explanation carries unrecognised fields.", frappe.ValidationError)
	missing = _EXPLANATION_FIELDS - set(explanation)
	if missing:
		frappe.throw("Explanation is missing required fields.", frappe.ValidationError)

	validated: dict[str, Any] = {}
	for field in _EXPLANATION_STR_FIELDS:
		value = str(explanation.get(field) or "").strip()
		if not value or len(value) > _EXPLANATION_STR_MAX_CHARS:
			frappe.throw(f"Explanation field '{field}' is invalid.", frappe.ValidationError)
		validated[field] = value
	for field in _EXPLANATION_LIST_FIELDS:
		items = explanation.get(field)
		if not isinstance(items, list) or len(items) > _EXPLANATION_LIST_MAX_ITEMS:
			frappe.throw(f"Explanation field '{field}' is invalid.", frappe.ValidationError)
		cleaned = []
		for item in items:
			text = str(item or "").strip()
			if not text or len(text) > _EXPLANATION_ITEM_MAX_CHARS:
				frappe.throw(f"Explanation field '{field}' has an invalid item.", frappe.ValidationError)
			cleaned.append(text)
		validated[field] = cleaned
	return validated


def _canonical_explanation(explanation: dict[str, Any]) -> str:
	return json.dumps(explanation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def set_recommendation_rationale(*, recommendation: str, explanation: object, source: str) -> dict[str, Any]:
	"""Fenced, idempotent, write-once explanation set on one ``CRM Recommendation``.

	Called by the agent service strictly after ``commit_nba_evaluation_result``
	already accepted the evaluation; this never touches score, rank, timing,
	action or disposition -- none of those are parameters here. A row-level
	lock plus a compare-and-swap on ``explanation`` being currently empty makes
	the write idempotent on retry and rejects a differing overwrite.
	"""
	_service_only()

	source = str(source or "").strip()
	if source not in _RATIONALE_SOURCES:
		frappe.throw("Unrecognised rationale source.", frappe.ValidationError)
	validated = _validated_explanation(explanation)
	canonical = _canonical_explanation(validated)

	if not frappe.db.exists("CRM Recommendation", recommendation):
		frappe.throw("Recommendation not found.", frappe.DoesNotExistError)

	frappe.db.sql("SELECT name FROM `tabCRM Recommendation` WHERE name=%s FOR UPDATE", (recommendation,))
	current_raw = frappe.db.get_value("CRM Recommendation", recommendation, "explanation")
	current = (current_raw or "").strip()
	if current:
		try:
			current_canonical = _canonical_explanation(frappe.parse_json(current))
		except Exception:
			current_canonical = current
		if current_canonical == canonical:
			return {"status": "unchanged", "recommendation": recommendation}
		frappe.throw("Recommendation explanation is already set and cannot change.", frappe.ValidationError)

	frappe.db.sql(
		"UPDATE `tabCRM Recommendation` SET explanation=%s, rationale_source=%s "
		"WHERE name=%s AND (explanation IS NULL OR explanation='')",
		(canonical, source, recommendation),
	)
	if frappe.db.sql("SELECT ROW_COUNT() AS affected", as_dict=True)[0].affected != 1:
		# Lost the CAS race between the read above and this fenced update.
		frappe.throw("Recommendation explanation was set concurrently.", frappe.ValidationError)
	if not frappe.flags.in_test:
		frappe.db.commit()
	return {"status": "set", "recommendation": recommendation}


# --------------------------------------------------------------------------- #
# Reconciliation (scheduler)
# --------------------------------------------------------------------------- #
def reconcile(limit: int = 200) -> dict[str, Any]:
	"""Recover expired leases and re-emit the outbox signal for stuck runs.

	Guarded on the feature flag so a disabled site does nothing. Reopening the
	same outbox record is safe: claim and settlement are fenced by a generation
	and a lease token, so delivery is intentionally at-least-once.
	"""
	if not nba_evaluation_runtime_enabled():
		return {"requeued": 0, "expired_leases": 0, "enabled": False}
	now = _lease_now()
	page = min(int(limit), 500)
	expired = frappe.get_all(
		DOCTYPE,
		filters={"status": "running", "lease_expires_at": ["<=", now]},
		pluck="name",
		limit_page_length=page,
	)
	for name in expired:
		frappe.db.sql(
			"UPDATE `tabCRM NBA Evaluation` SET status='queued', lease_token=NULL, lease_expires_at=NULL "
			"WHERE name=%s AND status='running' AND lease_expires_at IS NOT NULL AND lease_expires_at <= %s",
			(name, now),
		)
	requeued = 0
	from crm.api.agent_events import _enqueue_delivery, record_nba_evaluation_event

	for name in frappe.get_all(DOCTYPE, filters={"status": "queued"}, pluck="name", limit_page_length=page):
		event_name = frappe.db.get_value(
			"CRM Agent Event", {"delivery_key": f"nba-evaluation:{name}"}, "name"
		)
		if not event_name:
			record_nba_evaluation_event(frappe.get_doc(DOCTYPE, name))
			requeued += 1
			continue
		# A queued run whose signal is no longer making progress (delivered but
		# lost, dead-lettered, or wedged in processing) is reopened. Claim and
		# settlement stay fenced by generation + lease token, so redelivery is
		# safe at-least-once.
		frappe.db.sql(
			"UPDATE `tabCRM Agent Event` SET status='pending', next_attempt_at=%s, lease_id=NULL, lease_expires_at=NULL "
			"WHERE name=%s AND status IN ('delivered', 'dead_letter', 'cancelled', 'processing')",
			(now_datetime(), event_name),
		)
		if frappe.db.sql("SELECT ROW_COUNT() AS affected", as_dict=True)[0].affected:
			_enqueue_delivery(frappe.get_doc("CRM Agent Event", event_name))
			requeued += 1
	return {"requeued": requeued, "expired_leases": len(expired), "enabled": True}


def _request_automatic_nba_evaluation(
	student: str, *, trigger_reason: str, on_locked: Callable[[], None] | None = None
) -> str | None:
	"""Coalesced, server-side automatic evaluation request for a time/domain trigger.

	Unlike :func:`request_nba_evaluation` this carries no requester identity, no
	Idempotency-Key and no manual quota -- it is fired by the scheduler, not a
	user. Coalescing is the same single-active-run-per-identity invariant that
	:func:`_single_active` enforces: the Student row is locked first, and a fresh
	request over an identity that already has a queued or running run is dropped.
	Returns the new evaluation name, or ``None`` when a run already covers the
	identity or the runtime is disabled.

	``on_locked``, when given, runs immediately after the Student-row lock is
	acquired and before any other read of evaluation state -- a caller that
	needs its own consistent read of ``CRM NBA Evaluation`` (e.g. to find
	rows to mark dispatched) must do it here, not before this call, or its
	plain read pins the REPEATABLE READ snapshot ahead of the lock and can
	miss a concurrently committed run.
	"""
	if not nba_evaluation_runtime_enabled():
		return None
	if not student or not frappe.db.exists("CRM Student", student):
		return None
	frappe.db.sql("SELECT name FROM `tabCRM Student` WHERE name=%s FOR UPDATE", (student,))
	if on_locked:
		on_locked()
	clock = _request_clock()
	_, identity = _identity_for(student, clock)
	evaluation_key = identity["evaluation_key"]
	if _single_active(student, evaluation_key):
		return None
	if _latest_terminal(student, evaluation_key):
		# The governed identity has not moved since a run already settled it; a
		# time trigger only earns a fresh run once the identity (clock included)
		# changes, which it does on the next quantised minute.
		return None
	evaluation = _insert_evaluation(student, identity, clock, None, trigger="automatic")
	from crm.api.agent_events import record_nba_evaluation_event

	record_nba_evaluation_event(evaluation)
	return evaluation.name


def request_domain_reevaluation(student: str, *, trigger_reason: str) -> dict[str, Any]:
	"""Coalesced NBA re-evaluation request for a domain event (student state
	change, new interaction, ...), the counterpart of the WAIT revisit_at time
	trigger in :func:`reconcile_due_reevaluations`.

	Reuses :func:`_request_automatic_nba_evaluation` unchanged: its Student-row
	lock and single-active-run-per-identity check is the coalescing primitive.
	A domain event for a student that already has a queued or running
	Evaluation, or whose governed identity has not moved since the latest
	terminal run, merges into that run -- no new Evaluation is created and no
	duplicate concurrent run is started. A completed WAIT boundary that named
	this exact trigger and carries no ``revisit_at`` (the domain-event
	counterpart of the time-based boundary) is stamped dispatched so a later
	domain event of the same name never re-fires it.
	"""
	if not nba_evaluation_runtime_enabled():
		return {"enabled": False, "created": None, "coalesced": False, "matched_waits": 0}
	if not student or not frappe.db.exists("CRM Student", student):
		return {"enabled": True, "created": None, "coalesced": False, "matched_waits": 0}
	trigger_reason = str(trigger_reason or "").strip()[:140]
	if not trigger_reason:
		return {"enabled": True, "created": None, "coalesced": False, "matched_waits": 0}

	# The matching WAIT-row read is a plain consistent read of evaluation state;
	# it must run only after `_request_automatic_nba_evaluation` has acquired the
	# Student-row lock (its first statement), or it pins the REPEATABLE READ
	# snapshot ahead of the lock and can miss a concurrently committed run.
	matched: list[str] = []

	def _find_matching_waits() -> None:
		matched.extend(
			frappe.get_all(
				DOCTYPE,
				filters={
					"student": student,
					"status": "completed",
					"disposition": "WAIT",
					"revisit_at": ["is", "not set"],
					"reevaluation_trigger": trigger_reason,
					"reevaluation_dispatched_at": ["is", "not set"],
				},
				pluck="name",
				limit_page_length=20,
			)
		)

	created = _request_automatic_nba_evaluation(
		student, trigger_reason=f"domain-event:{trigger_reason}", on_locked=_find_matching_waits
	)
	# Only stamp a matched WAIT row when this event actually produced or merged
	# into a run. When `created` is None because the runtime is disabled, the
	# student vanished mid-lock, or the identity is unchanged since the last
	# terminal run, stamping here would permanently exclude the WAIT row from
	# both `reconcile_due_reevaluations` and future domain-event matching --
	# losing the trigger with no run ever created. Leaving it unstamped lets a
	# later event (or the identity moving) retry the boundary.
	if matched and created is not None:
		now = now_datetime()
		for name in matched:
			frappe.db.set_value(DOCTYPE, name, "reevaluation_dispatched_at", now, update_modified=False)
	return {
		"enabled": True,
		"created": created,
		# A domain event that found an already-active or identity-unchanged
		# terminal run made no new Evaluation; it merged into the existing one.
		"coalesced": created is None,
		"matched_waits": len(matched),
	}


def reconcile_due_reevaluations(limit: int = 200) -> dict[str, Any]:
	"""Fire an automatic evaluation for every WAIT boundary whose revisit is due.

	Feature-gated, so a site without the durable runtime does nothing. Each due
	WAIT row is stamped with ``reevaluation_dispatched_at`` after one pass so it
	is never rescanned, and the per-identity coalescing in
	:func:`_request_automatic_nba_evaluation` collapses many due rows for one
	student into a single fresh run. Pure event-name WAIT triggers (a null
	``revisit_at``) are handled by the domain-event admission path, not here.
	"""
	if not nba_evaluation_runtime_enabled():
		return {"dispatched": 0, "due": 0, "enabled": False}
	now = now_datetime()
	page = min(int(limit), 500)
	due = frappe.get_all(
		DOCTYPE,
		filters={
			"status": "completed",
			"disposition": "WAIT",
			"reevaluation_dispatched_at": ["is", "not set"],
			"revisit_at": ["<=", now],
		},
		fields=["name", "student"],
		order_by="revisit_at asc",
		limit_page_length=page,
	)
	dispatched = 0
	for row in due:
		try:
			created = _request_automatic_nba_evaluation(
				row.student, trigger_reason=f"wait-revisit:{row.name}"
			)
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title="NBA WAIT re-evaluation dispatch failed", message=f"evaluation={row.name}")
			continue
		frappe.db.set_value(DOCTYPE, row.name, "reevaluation_dispatched_at", now, update_modified=False)
		if created:
			dispatched += 1
	return {"dispatched": dispatched, "due": len(due), "enabled": True}
