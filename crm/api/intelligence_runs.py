"""Named, scoped Intelligence Run commands exposed to the CRM gateway."""
from __future__ import annotations

import frappe

from crm.fcrm import intelligence_runs


@frappe.whitelist(methods=["POST"])
def request_student_analysis_run(student: str, idempotency_key: str | None = None, force_reason: str | None = None):
	return intelligence_runs.request_run(
		domain="student", target=student, idempotency_key=idempotency_key or frappe.get_request_header("Idempotency-Key"), force_reason=force_reason
	)


@frappe.whitelist(methods=["POST"])
def request_school_analysis_run(high_school: str, idempotency_key: str | None = None, force_reason: str | None = None, admission_year: int | None = None):
	return intelligence_runs.request_run(
		domain="school", target=high_school, idempotency_key=idempotency_key or frappe.get_request_header("Idempotency-Key"), force_reason=force_reason, admission_year=admission_year
	)


@frappe.whitelist()
def get_analysis_run(run_type: str, run_id: str):
	if run_type not in intelligence_runs.RUN_TYPES.values():
		frappe.throw("Invalid Intelligence Run type.", frappe.ValidationError)
	run = frappe.get_doc(run_type, run_id)
	target_type, target = ("CRM Student", run.student) if run_type == "CRM Student Analysis Run" else ("CRM High School", run.high_school)
	if not frappe.has_permission(target_type, "read", target):
		frappe.throw("Intelligence Run target is outside current scope.", frappe.PermissionError)
	stages = frappe.get_all("CRM Analysis Run Stage", filters={"parent_run_type": run_type, "parent_run": run_id}, fields=["name", "stage_kind", "status", "claims", "terminal_reason", "policy_revision", "model_revision"])
	for stage in stages:
		stage["claims"] = intelligence_runs.visible_claims(stage.get("claims"))
	return {"run_id": run.name, "run_type": run_type, "status": run.status, "stages": stages}


@frappe.whitelist()
def get_analysis_request_receipt(request_id: str):
	return intelligence_runs.read_receipt(request_id)


@frappe.whitelist(methods=["POST"])
def get_analysis_evidence(run_type: str, run_id: str, stage_kind: str, stage_generation: int, lease_token: str):
	return intelligence_runs.service_evidence(
		run_type, run_id, stage_kind, int(stage_generation), lease_token
	)


@frappe.whitelist(methods=["POST"])
def get_analysis_run_execution(run_type: str, run_id: str):
	"""Service-only generic-signal materialization; never exposes CRM evidence."""
	return intelligence_runs.execution(run_type, run_id)


@frappe.whitelist(methods=["POST"])
def claim_analysis_stage(run_type: str, run_id: str, stage_kind: str, stage_generation: int):
	"""Acquire a fenced service-only stage lease before AI execution."""
	return intelligence_runs.claim_stage(
		run_type=run_type, run_id=run_id, stage_kind=stage_kind, stage_generation=int(stage_generation)
	)


@frappe.whitelist(methods=["POST"])
def settle_analysis_stage(
	run_type: str,
	run_id: str,
	stage_kind: str,
	stage_generation: int,
	lease_token: str,
	expected_source_revision: str,
	expected_source_digest: str,
	status: str,
	claims=None,
	terminal_reason: str | None = None,
	policy_revision: str | None = None,
	model_revision: str | None = None,
):
	"""Terminal-only, fenced worker settlement.

	``claimed: false, deferred: true`` from ``claim_analysis_stage`` means the
	worker must defer until ``retry_after``; it must not settle another worker's
	lease.  ``dead_lettered`` is a normal terminal settlement for exhausted
	retries and must include a bounded terminal reason.
	"""
	return intelligence_runs.settle_stage(
		run_type=run_type,
		run_id=run_id,
		stage_kind=stage_kind,
		stage_generation=int(stage_generation),
		lease_token=lease_token,
		expected_source_revision=expected_source_revision,
		expected_source_digest=expected_source_digest,
		status=status,
		claims=claims,
		terminal_reason=terminal_reason,
		policy_revision=policy_revision,
		model_revision=model_revision,
	)


@frappe.whitelist(methods=["POST"])
def upsert_next_best_action_from_analysis_run(
	run_id: str,
	stage_generation: int,
	lease_token: str,
	expected_source_revision: str,
	expected_source_digest: str,
	generation_idempotency_key: str,
	producer_identity: str,
	payload_digest: str,
	rollout_epoch: int,
	candidate: dict | str,
	writer_epoch: int | None = None,
):
	"""The only new NBA write shape: parent run + live stage lease, never a key.

	The legacy Student Decision endpoint remains an adapter during cutover, but
	when the Intelligence writer epoch is enabled it delegates through exactly
	the same Frappe authority checks.
	"""
	authority = intelligence_runs.authorize_next_best_action_write(
		run_id=run_id,
		stage_generation=int(stage_generation),
		lease_token=lease_token,
		expected_source_revision=str(expected_source_revision),
		expected_source_digest=expected_source_digest,
	)
	from crm.api.student_decision import _upsert_crm_action
	return _upsert_crm_action(
		student=authority["student"], expected_context_revision=int(expected_source_revision),
		generation_idempotency_key=generation_idempotency_key, producer_identity=producer_identity,
		payload_digest=payload_digest, rollout_epoch=int(rollout_epoch), candidate=candidate,
		writer_epoch=writer_epoch, source_stage_key=authority["stage_key"], run_id=run_id,
		stage_kind="next_best_action", stage_generation=int(stage_generation), lease_token=lease_token,
		expected_source_digest=expected_source_digest,
	)
