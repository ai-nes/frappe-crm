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

from crm.fcrm.analysis_runs import (
	canonical_request_fingerprint,
	validate_claim_set,
	validate_execution_revisions,
)
from crm.fcrm.permissions import has_permission as has_student_permission
from crm.fcrm.school_intelligence import get_school_intelligence
from crm.fcrm.scoring_projection import score_band

SERVICE_USER_KEY = "crm_agents_service_user"
RUN_TYPES = {"student": "CRM Student Analysis Run", "school": "CRM School Analysis Run"}
STAGES = {"student": ("student_360",), "school": ("school_360",)}
TERMINAL = {"completed", "abstained", "failed", "dead_lettered"}
ACTIVE = {"queued", "running"}
STUDENT_360_POLICY_REVISION = "student-360-analysis-r3"
STUDENT_360_SNAPSHOT_SCHEMA_VERSION = "student-360-snapshot-v1"
_STUDENT_ACTION_ADVICE = re.compile(
	r"(?:\b(?:nên|hãy|ưu tiên|đề xuất|khuyến nghị)\b[^.\n]{0,80}"
	 r"\b(?:gọi|liên hệ|liên lạc|gửi|đặt lịch|tư vấn|theo dõi|thực hiện)\b"
	 r"|\b(?:cần)\b[^.\n]{0,40}\b(?:gọi|liên hệ|liên lạc|gửi|đặt lịch|tư vấn|thực hiện)\b"
	 r"|(?:^|[.;:]\s*)(?:gọi|liên hệ|liên lạc|gửi|đặt lịch|tư vấn|theo dõi)\b[^.\n]{0,100})",
	re.IGNORECASE | re.MULTILINE,
)
_STUDENT_UNSAFE_ANALYSIS_LANGUAGE = (
	"qua phân tích toàn diện",
	"có thể suy ra rằng",
	"khả năng nhập học",
	"khả năng chuyển đổi",
	"xác suất nhập học",
	"student",
	"application momentum",
	"scholarship interest",
)
PROVENANCE_DOCTYPES = {
	"student": "CRM Student",
	"school": "CRM High School",
	"snapshot": "CRM High School Annual Snapshot",
	"stakeholder": "CRM School Stakeholder",
	"activity": "CRM School Activity",
	"recommendation": "CRM Recommendation",
	"score": "CRM Score History",
	"interaction": "CRM Interaction",
	"application": "CRM Admission Application",
	"guardian": "CRM Student Guardian",
	"lifecycle": "CRM Student Lifecycle Event",
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
	if domain == "student":
		target_doc = frappe.get_doc(doctype, target)
		permitted = has_student_permission(target_doc, user=frappe.session.user, permission_type="read")
	else:
		permitted = frappe.has_permission(doctype, "read", target)
	if not permitted:
		frappe.throw("Intelligence Run target is outside current scope.", frappe.PermissionError)


def _source(domain: str, target: str, admission_year: int | None = None) -> tuple[str, str]:
	if domain == "student":
		revision = str(int(frappe.db.get_value("CRM Student", target, "student_context_revision") or 0))
		evidence = _student_stage_evidence(target, revision).get("student_360")
		if not isinstance(evidence, dict):
			frappe.throw("Student 360 source evidence is unavailable.", frappe.ValidationError)
		return revision, _digest(_student_360_analysis_input(evidence))
	# Never hash ``get_school_intelligence`` here.  That is a reader projection
	# and deliberately changes with the caller's permissions.  A run identity is
	# service-owned: the school aggregate's monotonic journal revision is the
	# authoritative snapshot cursor, while permission filtering happens only when
	# a persisted claim is rendered to a reader.
	journal_revision = str(int(frappe.db.get_value("CRM High School", target, "intelligence_revision") or 0))
	return journal_revision, _digest({"domain": "school", "high_school": target, "revision": journal_revision, "admission_year": admission_year or None})


def _student_360_analysis_input(evidence: dict[str, Any]) -> dict[str, Any]:
	"""The only fields that invalidate a Student 360 AI snapshot.

	Live journal presentation (actor, summary, task) and score presentation
	(band, trend, contributors) are deliberately excluded: they never enter the
	model snapshot.  Policy revision is included because it can alter meaning.
	"""
	signals = evidence.get("signals") if isinstance(evidence.get("signals"), dict) else {}
	return {
		"policy_revision": STUDENT_360_POLICY_REVISION,
		"student_state": {key: signals.get(key) for key in (
			"student_stage", "study_stage", "assessment_status",
			"interest", "fit",
			"primary_barrier", "intent_type", "intent_polarity", "sla_state", "score",
		)},
		"score_history": signals.get("score_history") or [],
		"verified_interactions": signals.get("interaction_history") or [],
		"applications": signals.get("applications") or [],
		"guardian_signals": signals.get("guardian_signals") or [],
	}


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


def _parse_mapping(value: Any) -> dict[str, Any] | None:
	if isinstance(value, dict):
		return value
	if not value:
		return None
	try:
		parsed = frappe.parse_json(value)
	except Exception:
		return None
	return parsed if isinstance(parsed, dict) else None


def _public_report(value: Any, *, claims_visible: bool) -> dict[str, Any] | None:
	"""Project the legacy School 360 report shape for School consumers only."""
	report = _parse_mapping(value)
	if report is None:
		return None

	def items(raw: Any, *, allowed_kinds: set[str]) -> list[dict[str, Any]]:
		result: list[dict[str, Any]] = []
		for item in raw if isinstance(raw, list) else []:
			if not isinstance(item, dict) or item.get("kind") not in allowed_kinds:
				continue
			refs = item.get("provenance_ids") or item.get("evidence_refs") or []
			if not isinstance(refs, list) or not refs or not _claim_visible(refs):
				continue
			headline = str(item.get("headline") or item.get("title") or "").strip()
			detail = str(item.get("detail") or item.get("summary") or "").strip()
			if not headline or not detail:
				continue
			entry = {
				"kind": item["kind"], "headline": headline[:240], "detail": detail[:900],
				"provenance_ids": refs[:8],
			}
			if isinstance(item.get("confidence"), (int, float)) and not isinstance(item.get("confidence"), bool):
				entry["confidence"] = float(item["confidence"])
			else:
				entry["confidence"] = None
			# These are presentation bands authored by the validated snapshot, not
			# scores computed by this reader.
			for key in ("severity", "strength"):
				if item.get(key) in {"LOW", "MEDIUM", "HIGH"}:
					entry[key] = item[key]
			result.append(entry)
		return result[:6]

	return {
		"title": report.get("title") if claims_visible and isinstance(report.get("title"), str) else None,
		# A summary has no independently addressable reference in legacy rows;
		# suppress it if no visible claim survives the same permission boundary.
		"summary": report.get("summary") if claims_visible and isinstance(report.get("summary"), str) else None,
		"risks": items(report.get("risks"), allowed_kinds={"risk"}),
		"recommendations": items(report.get("recommendations"), allowed_kinds={"recommendation", "opportunity"}),
		"missing_evidence": [str(item)[:240] for item in report.get("missing_evidence", []) if isinstance(item, str) and item.strip()][:12] if claims_visible else [],
		"advisory_signals": [],
		"opportunity_signals": [],
		"recent_changes": [],
	}


def _public_student_snapshot(value: Any, *, claims_visible: bool) -> dict[str, Any] | None:
	"""Project only the canonical Student 360 snapshot shape.

	Student 360 never falls back to the legacy ``kind/headline/detail`` report
	shape. A malformed or mixed-era report is hidden until a new snapshot is
	settled under the v1 contract.
	"""
	report = _parse_mapping(value)
	allowed_keys = {"advisory_signals", "risks", "opportunity_signals", "recent_changes"}
	if not report or set(report) != allowed_keys or not claims_visible:
		return None
	try:
		_validate_student_awareness_report(report)
	except Exception:
		# Historical or hand-written rows must never bypass the settlement
		# validator merely because they happen to contain the four section names.
		return None

	def refs(item: dict[str, Any]) -> list[str] | None:
		value = item.get("evidence_refs")
		if not isinstance(value, list) or not value or len(value) > 8:
			return None
		return [str(ref) for ref in value]

	def text(item: dict[str, Any], key: str, limit: int) -> str | None:
		value = item.get(key)
		return value.strip()[:limit] if isinstance(value, str) and value.strip() else None

	def advisory(raw: Any) -> list[dict[str, Any]]:
		result = []
		for item in raw if isinstance(raw, list) else []:
			if not isinstance(item, dict):
				continue
			evidence = refs(item)
			type_value = text(item, "type", 80)
			title = text(item, "title", 240)
			summary = text(item, "summary", 900)
			if not evidence or not type_value or not title or not summary or not _claim_visible(evidence):
				continue
			if item.get("confidence") not in {"LOW", "MEDIUM", "HIGH"}:
				continue
			result.append({"type": type_value, "title": title, "summary": summary, "confidence": item["confidence"], "evidence_refs": evidence})
		return result[:5]

	def findings(raw: Any, band: str, code_key: str) -> list[dict[str, Any]]:
		result = []
		for item in raw if isinstance(raw, list) else []:
			if not isinstance(item, dict):
				continue
			evidence = refs(item)
			code = text(item, code_key, 80)
			title = text(item, "title", 240)
			summary = text(item, "summary", 900)
			if not evidence or not code or not title or not summary or not _claim_visible(evidence):
				continue
			if item.get(band) not in {"LOW", "MEDIUM", "HIGH"}:
				continue
			result.append({code_key: code, band: item[band], "title": title, "summary": summary, "evidence_refs": evidence})
		return result[:3]

	def changes(raw: Any) -> list[dict[str, Any]]:
		result = []
		for item in raw if isinstance(raw, list) else []:
			if not isinstance(item, dict):
				continue
			evidence = refs(item)
			type_value = text(item, "type", 80)
			summary = text(item, "summary", 400)
			if evidence and type_value and summary and _claim_visible(evidence):
				result.append({"type": type_value, "summary": summary, "evidence_refs": evidence})
		return result[:3]

	return {
		"advisory_signals": advisory(report.get("advisory_signals")),
		"risks": findings(report.get("risks"), "severity", "code"),
		"opportunity_signals": findings(report.get("opportunity_signals"), "strength", "code"),
		"recent_changes": changes(report.get("recent_changes")),
	}


def _public_stage(stage: dict[str, Any], *, student: bool) -> dict[str, Any]:
	claims = visible_claims(stage.get("claims"))
	if student:
		# Old Student reports mixed awareness with action advice.  They remain in
		# storage for audit, but are not a public renderable 360 snapshot.
		# A fresh stage intentionally has no settlement policy yet.  Rendering it
		# as policy-superseded made a real queued/running run look terminal to the
		# FE although its worker still owned a lease.
		if stage.get("status") in TERMINAL and stage.get("status") == "completed" and stage.get("policy_revision") != STUDENT_360_POLICY_REVISION:
			return {
				"name": stage.get("name"), "stage_kind": stage.get("stage_kind"), "status": "abstained",
				"claims": [], "report": None, "terminal_reason": "policy_superseded",
				"policy_revision": stage.get("policy_revision") or None, "model_revision": stage.get("model_revision") or None,
			}
		claims = [claim for claim in claims if claim.get("kind") != "recommendation"]
	return {
		"name": stage.get("name"),
		"stage_kind": stage.get("stage_kind"),
		"status": stage.get("status"),
		"claims": claims,
		"report": _public_student_snapshot(stage.get("report_json"), claims_visible=bool(claims)) if student else _public_report(stage.get("report_json"), claims_visible=bool(claims)),
		"terminal_reason": stage.get("terminal_reason") or None,
		"policy_revision": stage.get("policy_revision") or None,
		"model_revision": stage.get("model_revision") or None,
	}


def public_run_payload(run, *, receipt: Any | None = None, reused_existing_run: bool = False) -> dict[str, Any]:
	"""Return the FE-compatible presentation of one real Analysis Run."""
	is_student = run.doctype == RUN_TYPES["student"]
	stages = frappe.get_all(
		"CRM Analysis Run Stage", filters={"parent_run_type": run.doctype, "parent_run": run.name},
		fields=["name", "stage_kind", "status", "claims", "report_json", "policy_revision", "model_revision", "terminal_reason"],
		order_by="creation asc",
	)
	public_stages = [_public_stage(stage, student=is_student) for stage in stages if stage.get("stage_kind") in _stage_kinds_for(run.doctype)]
	if is_student:
		public_stages = [stage for stage in public_stages if stage.get("stage_kind") == "student_360"]
	return {
		"run_id": run.name, "run_type": run.doctype, "status": run.status,
		"receipt": receipt.name if receipt else None,
		"source_revision": int(run.source_revision) if str(run.source_revision).isdigit() else None,
		"source_digest": run.get("source_digest") or None,
		"expires_at": str(receipt.expires_at) if receipt and receipt.get("expires_at") else None,
		"reused_existing_run": bool(reused_existing_run), "stages": public_stages,
	}


def _receipt(receipt, *, reused_existing_run: bool = False) -> dict[str, Any]:
	run = frappe.get_doc(receipt.parent_run_type, receipt.parent_run)
	return public_run_payload(run, receipt=receipt, reused_existing_run=reused_existing_run)


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


def require_analysis_run_enabled(domain: str) -> None:
	"""Gate Student 360 independently from the retired NBA child writer."""
	if domain == "student":
		if frappe.conf.get("crm_intelligence_runs_enabled", 0) not in (1, "1", True):
			frappe.throw("Student Intelligence Run cutover is not enabled.", frappe.ValidationError)
		return
	require_unified_intelligence_enabled()


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


def _analysis_policy_revision(domain: str) -> str | None:
	return STUDENT_360_POLICY_REVISION if domain == "student" else None


def _supersede_active_student_run(run) -> None:
	"""Fence a mismatched Student refresh before a new current run is created."""
	frappe.db.sql(
		"UPDATE `tabCRM Analysis Run Stage` SET status='abstained', claims='[]', report_json=NULL, "
		"terminal_reason='superseded', lease_token=NULL, lease_expires_at=NULL "
		"WHERE parent_run_type=%s AND parent_run=%s AND status IN ('queued', 'running')",
		(RUN_TYPES["student"], run.name),
	)
	run.db_set("status", "abstained", update_modified=False)
	run.db_set("terminal_reason", "superseded", update_modified=False)


def request_run(*, domain: str, target: str, idempotency_key: str, force_reason: str | None = None, admission_year: int | None = None) -> dict[str, Any]:
	"""Create/reuse a scoped manual run; no caller credential is persisted."""
	require_analysis_run_enabled(domain)
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
	policy_revision = _analysis_policy_revision(domain)
	payload = {"domain": domain, "target": target, "source_revision": revision, "trigger": "manual"}
	if policy_revision:
		payload["policy_revision"] = policy_revision
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
		return _receipt(receipt, reused_existing_run=True)
	run_type = RUN_TYPES[domain]
	reused_existing_run = False
	active_run = _active_run(domain, target)
	if active_run:
		# A force flag never bypasses the single-active-run fence.  It is for a
		# completed/abstained revision whose analyst needs an auditable rerun.
		if domain == "student" and (
			active_run.source_digest != source_digest
			or (active_run.get("policy_revision") or None) != policy_revision
		):
			_supersede_active_student_run(active_run)
			active_run = None
		else:
			run = active_run
			reused_existing_run = True
	if not active_run and not force_reason:
		# A normal button press is a request for the current analysis, not an
		# instruction to spend another model call.  Reuse any terminal result for
		# precisely this authoritative revision; an explicit privileged force is
		# the only way to rerun it.
		field = "student" if domain == "student" else "high_school"
		matching_terminal = frappe.get_all(
			run_type,
			filters={field: target, "source_digest": source_digest, "status": "completed", "policy_revision": policy_revision},
			pluck="name",
			order_by="creation desc",
			limit_page_length=1,
		)
		run = frappe.get_doc(run_type, matching_terminal[0]) if matching_terminal else None
		reused_existing_run = run is not None
		if not run:
			_enforce_manual_quota(domain, target)
			run = _insert_run(domain, target, revision, source_digest, fingerprint, admission_year, policy_revision=policy_revision)
	elif not active_run:
		_enforce_manual_quota(domain, target)
		run = _insert_run(domain, target, revision, source_digest, fingerprint, admission_year, policy_revision=policy_revision)
	receipt = frappe.get_doc({"doctype": "CRM Analysis Request Receipt", "requester": frappe.session.user, "idempotency_key": key, "request_fingerprint": fingerprint, "parent_run_type": run_type, "parent_run": run.name, "expires_at": add_to_date(now_datetime(), hours=24)}).insert(ignore_permissions=True)
	return _receipt(receipt, reused_existing_run=reused_existing_run)


def request_automatic_run(domain: str, target: str, admission_year: int | None = None, admission_decision: str | None = None, admission_event: str | None = None, candidate_revision: int | None = None, policy_revision: str | None = None):
	"""Create one idempotent automatic parent for an authoritative revision."""
	require_unified_intelligence_enabled()
	if domain not in RUN_TYPES:
		raise ValueError("invalid Intelligence Run domain")
	if domain == "student":
		# Student 360 is request-driven.  Keep the helper for School 360 and for
		# backward-compatible callers, but never silently create Student work.
		return None
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
	return run


def _insert_run(domain, target, revision, source_digest, fingerprint, admission_year, *, trigger="manual", admission_decision=None, admission_event=None, candidate_revision=None, policy_revision=None):
	run_type = RUN_TYPES[domain]
	values = {"doctype": run_type, "source_revision": revision, "source_digest": source_digest, "analysis_input_digest": source_digest, "trigger": trigger, "status": "queued", "request_fingerprint": fingerprint}
	if trigger == "manual":
		values["requested_by"] = frappe.session.user
	if policy_revision:
		values["policy_revision"] = policy_revision
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
	"""Return only the bounded, no-PII evidence surface for Student 360."""
	row = frappe.db.get_value(
		"CRM Student", student,
		[
			"student_stage", "current_grade", "study_stage",
			"assessment_status", "interest_level", "fit_level", "primary_barrier",
			"latest_score", "sla_evidence_state", "score_input_revision", "applied_score_input_revision",
		],
		as_dict=True,
	) or {}
	# Context packs are bounded and intentionally exclude names, contact data,
	# notes, summaries and linked document identifiers.  They provide the model
	# the temporal/decision context needed for a useful 360 analysis while
	# preserving the service-only permission boundary.
	def _rows(doctype, fields, limit, order_by="creation desc, name desc", extra_filters=None):
		if not frappe.db.table_exists(doctype):
			return []
		filters = {"student": student, **(extra_filters or {})}
		return frappe.get_all(doctype, filters=filters, fields=["name", *fields],
			limit_page_length=limit, order_by=order_by, ignore_permissions=True)

	def _ref(prefix, item):
		name = item.get("name")
		return [f"{prefix}:{name}"] if name else []

	score_history = _rows("CRM Score History", [
		"scoring_time", "scoring_date", "final_score", "score_change", "fit_score",
		"engagement_score", "intent_score",
	], 12, "scoring_time desc, creation desc, name desc")
	# Legacy score rows may only have scoring_time.  The agent evidence contract
	# requires a bounded temporal reference, so normalize at the producer edge.
	for item in score_history:
		item["scoring_date"] = str(item.get("scoring_date") or item.get("scoring_time") or "unknown")
		item.pop("scoring_time", None)
		# The model must reason from the same LOW/MEDIUM/HIGH bands the dashboard
		# uses (`score_band`), not raw floats -- otherwise the numerically
		# largest of several low components reads as a positive absolute signal.
		item["fit_band"] = score_band(item.get("fit_score"))
		item["engagement_band"] = score_band(item.get("engagement_score"))
		item["intent_band"] = score_band(item.get("intent_score"))
		contributors = []
		try:
			for detail in frappe.get_doc("CRM Score History", item.get("name")).get("details") or []:
				if detail.get("category") or detail.get("signal"):
					contributors.append(
						{
							"category": detail.get("category"),
							"signal": detail.get("signal"),
							"score": detail.get("score"),
						}
					)
		except Exception:
			contributors = []
		item["contributors"] = contributors[:6]
	interactions = _rows("CRM Interaction", [
		"interaction_datetime", "interaction_type", "channel", "direction", "outcome", "source_verified",
	], 20, "interaction_datetime desc, creation desc, name desc", {"source_verified": 1})
	intents = _rows("CRM Intent", ["interaction", "intent_type", "polarity"], 20, "creation desc, name desc")
	intents_by_interaction = {
		item.get("interaction"): item
		for item in intents
		if item.get("interaction")
	}
	latest_interaction = interactions[0] if interactions else {}
	latest_intent = intents_by_interaction.get(latest_interaction.get("name")) or {}
	input_revision = int(row.get("score_input_revision") or 0)
	applied_score_revision = int(row.get("applied_score_input_revision") or 0)
	applications = _rows("CRM Admission Application", [
		"status", "preference", "preference_order", "document_total",
		"document_completed", "scholarship_percentage", "deadline",
	], 8, "creation desc, name desc")
	guardians = _rows("CRM Student Guardian", [
		"relationship", "decision_role", "involvement", "preferred_channel", "is_active",
	], 8, "creation desc, name desc")
	# This is evidence, not a conclusion: the AI handler must derive and label
	# any inference/uncertainty it publishes.  No name, phone, email, notes,
	# free-form interaction text, or recipient data crosses this boundary.
	student_360 = {
		"signals": {
			# This is the only CRM stage axis used by Student 360.  Never infer it
			# from legacy lifecycle data or the academic study stage.
			"student_stage": row.get("student_stage"),
			"study_stage": row.get("study_stage") or row.get("current_grade"),
			"assessment_status": row.get("assessment_status"),
			"interest": row.get("interest_level"),
			"fit": row.get("fit_level"),
			"primary_barrier": row.get("primary_barrier"),
			"score": row.get("latest_score"),
		# The decision projection uses ``pending`` while a score is being
		# calculated; the analysis evidence contract intentionally exposes only
		# its bounded freshness vocabulary.
			"score_freshness": "pending" if input_revision > applied_score_revision else "fresh",
			"intent_type": latest_intent.get("intent_type"),
			"intent_polarity": latest_intent.get("polarity"),
			"latest_interaction_outcome": latest_interaction.get("outcome"),
			"sla_state": row.get("sla_evidence_state"),
			"score_history": [
				{
					"scoring_date": item.get("scoring_date") or item.get("scoring_time"),
					"final_score": item.get("final_score"),
					"score_change": item.get("score_change"),
					"fit_score": item.get("fit_score"),
					"fit_band": item.get("fit_band"),
					"engagement_score": item.get("engagement_score"),
					"engagement_band": item.get("engagement_band"),
					"intent_score": item.get("intent_score"),
					"intent_band": item.get("intent_band"),
					"contributors": item.get("contributors") or [],
					"provenance_ids": _ref("score", item),
				}
				for item in score_history
			],
			"interaction_history": [
				{
					"interaction_date": item.get("interaction_datetime"),
					"channel": item.get("channel"),
					"topics": [item.get("interaction_type")] if item.get("interaction_type") else [],
					"intent_type": (intents_by_interaction.get(item.get("name")) or {}).get("intent_type"),
					"intent_polarity": (intents_by_interaction.get(item.get("name")) or {}).get("polarity"),
					"barriers": [row.get("primary_barrier")] if row.get("primary_barrier") else [],
					"direction": item.get("direction"),
					"outcome": item.get("outcome"),
					"source_verified": item.get("source_verified"),
					"provenance_ids": _ref("interaction", item),
				}
				for item in interactions
			],
			"applications": [
				{"status": item.get("status"), "preference": item.get("preference"), "preference_order": item.get("preference_order"),
				 "document_total": item.get("document_total"), "document_completed": item.get("document_completed"),
				 "scholarship_percentage": item.get("scholarship_percentage"), "deadline": item.get("deadline"),
				 "provenance_ids": _ref("application", item)}
				for item in applications
			],
			"guardian_signals": [
				{"relationship": item.get("relationship"), "decision_role": item.get("decision_role"), "involvement": item.get("involvement"),
				 "preferred_channel": item.get("preferred_channel"), "is_active": item.get("is_active"), "provenance_ids": _ref("guardian", item)}
				for item in guardians
			],
		},
		"unknowns": [
			key for key, value in row.items()
			if key in {
				"student_stage", "assessment_status", "interest_level", "fit_level",
				"primary_barrier", "latest_score",
			}
			and value in (None, "")
		],
		"provenance_ids": [f"student:{student}"],
	}
	return {"student_360": student_360}


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


def _stage_lease_seconds() -> int:
	"""Return a bounded lease that permits retry shortly after the worker deadline.

	The former ten-minute implicit default left a timed-out 360 stage visibly
	"running" long after its local worker had released it.  Deployments may set
	seconds explicitly; the legacy minutes setting remains supported.
	"""
	configured_seconds = frappe.conf.get("crm_intelligence_stage_lease_seconds")
	if configured_seconds not in (None, ""):
		return min(max(int(configured_seconds), 45), 3600)
	configured_minutes = frappe.conf.get("crm_intelligence_stage_lease_minutes")
	if configured_minutes not in (None, ""):
		return min(max(int(configured_minutes) * 60, 45), 3600)
	return 60


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
	lease_until = now + timedelta(seconds=_stage_lease_seconds())
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


def settle_stage(*, run_type: str, run_id: str, stage_kind: str, stage_generation: int, lease_token: str, expected_source_revision: str, expected_source_digest: str, status: str, claims=None, terminal_reason: str | None = None, policy_revision: str | None = None, model_revision: str | None = None, result_digest: str | None = None, completed_metadata: dict | None = None, report=None) -> dict[str, Any]:
	_service_only()
	if status not in TERMINAL:
		frappe.throw("Only terminal stage settlement is allowed.", frappe.ValidationError)
	result_digest = _validated_result_digest(result_digest)
	if status == "completed" and not result_digest:
		frappe.throw("Completed Analysis Run stages require a result digest.", frappe.ValidationError)
	if status == "completed" and run_type == RUN_TYPES["student"]:
		_validate_student_awareness_report(report)
		if any(claim.get("kind") == "recommendation" for claim in (claims or [])):
			frappe.throw("Student 360 claims cannot contain recommendations.", frappe.ValidationError)
	report_json = json.dumps(report or {}, ensure_ascii=False, separators=(",", ":")) if report else None
	terminal_reason = str(terminal_reason).strip() if terminal_reason is not None else None
	if terminal_reason is not None and len(terminal_reason) > 500:
		frappe.throw("Analysis Run terminal reason is bounded.", frappe.ValidationError)
	if status in {"failed", "dead_lettered"} and not terminal_reason:
		frappe.throw("Failed or dead-lettered stages require a terminal reason.", frappe.ValidationError)
	validate_claim_set(claims)
	if status == "completed" and run_type == RUN_TYPES["student"]:
		_validate_student_awareness_claims(claims or [])
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
	if status == "completed" and run_type == RUN_TYPES["student"] and (run.get("policy_revision") or None) != (policy_revision or None):
		# A queued worker from the old recommendation-bearing policy must never
		# publish into the new awareness-only surface.  Fence it terminal rather
		# than retrying forever on a policy mismatch.
		status, terminal_reason, claims = "abstained", "policy_superseded", []
		policy_revision = model_revision = result_digest = None
		report_json = None
	domain = "student" if run_type == RUN_TYPES["student"] else "school"
	target = run.student if domain == "student" else run.high_school
	current_revision, current_digest = _source(domain, target, run.get("admission_year"))
	if current_revision != str(expected_source_revision) or current_digest != expected_source_digest:
		status, terminal_reason, claims, policy_revision, model_revision, result_digest = "abstained", "superseded", [], None, None, None
	frappe.db.sql(
		"UPDATE `tabCRM Analysis Run Stage` SET status=%s, claims=%s, report_json=%s, terminal_reason=%s, policy_revision=%s, model_revision=%s, result_digest=%s, analyzed_at=%s, lease_token=NULL, lease_expires_at=NULL "
		"WHERE name=%s AND status IN ('queued', 'running') AND stage_generation=%s "
		"AND lease_token=%s AND expected_source_revision=%s AND expected_source_digest=%s",
		(status, json.dumps(claims or []), report_json, terminal_reason, policy_revision, model_revision, result_digest, now_datetime() if status == "completed" else None, stage.name, int(stage_generation), str(lease_token or ""), str(expected_source_revision), expected_source_digest),
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


def _validate_student_awareness_report(report: Any) -> None:
	if not isinstance(report, dict):
		frappe.throw("Completed Student 360 requires a structured report.", frappe.ValidationError)
	allowed_sections = {"advisory_signals", "risks", "opportunity_signals", "recent_changes"}
	if set(report) != allowed_sections:
		frappe.throw("Student 360 report must use the v1 snapshot shape.", frappe.ValidationError)

	def _refs(item: dict[str, Any]) -> list[str]:
		refs = item.get("evidence_refs")
		if not isinstance(refs, list) or not 1 <= len(refs) <= 8 or len(set(refs)) != len(refs):
			frappe.throw("Student 360 snapshot evidence is invalid.", frappe.ValidationError)
		for ref in refs:
			prefix, separator, name = str(ref).partition(":")
			if not separator or prefix not in PROVENANCE_DOCTYPES or not name or len(str(ref)) > 140:
				frappe.throw("Student 360 snapshot evidence reference is invalid.", frappe.ValidationError)
		return refs

	def _summary(item: dict[str, Any], limit: int) -> str:
		value = item.get("summary")
		if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
			frappe.throw("Student 360 snapshot item text is invalid.", frappe.ValidationError)
		if len([part for part in re.split(r"[.!?]+", value) if part.strip()]) not in {1, 2}:
			frappe.throw("Student 360 snapshot item must contain one or two sentences.", frappe.ValidationError)
		return value.strip()

	def _text(item: dict[str, Any], key: str, limit: int) -> str:
		value = item.get(key)
		if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
			frappe.throw("Student 360 snapshot item text is invalid.", frappe.ValidationError)
		return value.strip()

	def _items(key: str, limit: int, required: set[str], band: str | None = None, code: str | None = None) -> list[dict[str, Any]]:
		items = report.get(key)
		minimum = 3 if key == "advisory_signals" else 0
		if not isinstance(items, list) or not minimum <= len(items) <= limit:
			frappe.throw("Student 360 snapshot section is invalid.", frappe.ValidationError)
		for item in items:
			if not isinstance(item, dict) or set(item) != required:
				frappe.throw("Student 360 snapshot item shape is invalid.", frappe.ValidationError)
			if code:
				_text(item, code, 80)
			if band and item.get(band) not in {"LOW", "MEDIUM", "HIGH"}:
				frappe.throw("Student 360 snapshot band is invalid.", frappe.ValidationError)
			if key == "advisory_signals":
				_text(item, "type", 80)
				_text(item, "title", 240)
			else:
				_text(item, "title", 240)
			_summary(item, 900)
			_refs(item)
		return items

	advisory = _items(
		"advisory_signals", 5,
		{"type", "title", "summary", "confidence", "evidence_refs"},
		band="confidence",
	)
	risks = _items(
		"risks", 3,
		{"code", "severity", "title", "summary", "evidence_refs"},
		band="severity",
		code="code",
	)
	opportunities = _items(
		"opportunity_signals", 3,
		{"code", "strength", "title", "summary", "evidence_refs"},
		band="strength",
		code="code",
	)
	changes = report.get("recent_changes")
	if not isinstance(changes, list) or len(changes) > 3:
		frappe.throw("Student 360 recent changes are invalid.", frappe.ValidationError)
	for item in changes:
		if not isinstance(item, dict) or set(item) != {"type", "summary", "evidence_refs"}:
			frappe.throw("Student 360 recent change shape is invalid.", frappe.ValidationError)
		_text(item, "type", 80)
		_summary(item, 400)
		_refs(item)

	visible_text = " ".join(
		_text(item, "title", 240) + " " + _summary(item, 900)
		for item in (*advisory, *risks, *opportunities)
	)
	visible_text += " " + " ".join(_summary(item, 400) for item in changes)
	if _STUDENT_ACTION_ADVICE.search(visible_text):
		frappe.throw("Student 360 report contains action advice.", frappe.ValidationError)
	normalized = visible_text.casefold()
	if any(phrase in normalized for phrase in _STUDENT_UNSAFE_ANALYSIS_LANGUAGE):
		frappe.throw("Student 360 report must stay compact, grounded, and awareness-only.", frappe.ValidationError)


def _validate_student_awareness_claims(claims: list[dict[str, Any]]) -> None:
	"""Keep the persisted Student claim compatibility layer awareness-only too."""
	visible_text = " ".join(
		str(claim.get("text", ""))
		for claim in claims
		if isinstance(claim, dict)
	)
	if _STUDENT_ACTION_ADVICE.search(visible_text):
		frappe.throw("Student 360 claims cannot contain action advice.", frappe.ValidationError)
