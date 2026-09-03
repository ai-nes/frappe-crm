"""Permission-aware reader for completed Student 360 analysis stages.

Next Best Action generation reasons from a completed, same-revision Student 360.
This module is the only read path for that stage's shareable claims and result
digest. It mirrors the Student row scope the framework enforces for
``student_worklist`` and the Intelligence Run reader, and the claim-suppression
rule from ``intelligence_runs.visible_claims``: a caller who cannot see the
Student, or cannot resolve every source a claim cites, gets nothing.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import get_datetime

from crm.fcrm.intelligence_runs import RUN_TYPES, visible_claims
from crm.fcrm.record_retention import technical_retention_cutoff

CONTRACT_VERSION = "student-360-read-v1"
_STUDENT_RUN_TYPE = RUN_TYPES["student"]
_OUT_OF_SCOPE = _("The requested Student 360 analysis is not available.")


def _require_authenticated() -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)


def _require_student_scope(student: str | None) -> None:
	# The framework check covers a missing DocType read grant, a User Permission,
	# permlevel, and share scope -- not just the row-scope query condition.
	if not student or not frappe.has_permission(
		"CRM Student", "read", student, user=frappe.session.user
	):
		frappe.throw(_OUT_OF_SCOPE, frappe.PermissionError)


def _retention_expired(run_creation) -> bool:
	if not run_creation:
		return False
	return get_datetime(run_creation) < get_datetime(technical_retention_cutoff("analysis_run"))


def _completed_student_360_stage(extra_filters: dict) -> dict | None:
	rows = frappe.get_all(
		"CRM Analysis Run Stage",
		filters={
			"parent_run_type": _STUDENT_RUN_TYPE,
			"stage_kind": "student_360",
			"status": "completed",
			**extra_filters,
		},
		fields=[
			"name",
			"parent_run",
			"expected_source_revision",
			"expected_source_digest",
			"result_digest",
			"policy_revision",
			"model_revision",
			"claims",
			"modified",
		],
		order_by="modified desc",
		limit_page_length=1,
	)
	return rows[0] if rows else None


def _stage_payload(stage: dict, run: dict) -> dict:
	retention_expired = _retention_expired(run.get("creation"))
	return {
		"contract_version": CONTRACT_VERSION,
		"run_id": run["name"],
		"run_type": _STUDENT_RUN_TYPE,
		"student": run["student"],
		"source_revision": str(stage.get("expected_source_revision")),
		"source_digest": stage.get("expected_source_digest"),
		"result_digest": stage.get("result_digest"),
		"status": "completed",
		"policy_revision": stage.get("policy_revision"),
		"model_revision": stage.get("model_revision"),
		"retention_expired": retention_expired,
		"claims": [] if retention_expired else visible_claims(stage.get("claims")),
		"settled_at": str(stage.get("modified")) if stage.get("modified") else None,
	}


def _not_available(student: str | None) -> dict:
	return {
		"contract_version": CONTRACT_VERSION,
		"run_type": _STUDENT_RUN_TYPE,
		"student": student,
		"status": "not_available",
		"claims": [],
	}


@frappe.whitelist()
def get_student_360(
	run_id: str | None = None,
	student: str | None = None,
	source_revision: str | int | None = None,
) -> dict:
	"""Return the completed Student 360 stage for a run, or for a student revision.

	Provide exactly one of: ``run_id``; or both ``student`` and
	``source_revision``. The response shape is versioned by ``contract_version``.
	An out-of-scope caller and an unknown run are indistinguishable.
	"""
	_require_authenticated()
	by_run = bool(run_id)
	by_revision = bool(student) and source_revision is not None
	if by_run == by_revision:
		frappe.throw(
			_("Provide either run_id, or both student and source_revision."),
			frappe.ValidationError,
		)

	if by_run:
		run = frappe.db.get_value(
			_STUDENT_RUN_TYPE, run_id, ["name", "student", "creation"], as_dict=True
		)
		# Resolve scope before revealing whether the run exists.
		_require_student_scope(run.student if run else None)
		if not run:
			frappe.throw(_OUT_OF_SCOPE, frappe.PermissionError)
		stage = _completed_student_360_stage({"parent_run": run["name"]})
		return _stage_payload(stage, run) if stage else _not_available(run["student"])

	_require_student_scope(student)
	run_names = frappe.get_all(
		_STUDENT_RUN_TYPE,
		filters={"student": student, "source_revision": str(source_revision)},
		pluck="name",
	)
	stage = _completed_student_360_stage({"parent_run": ["in", run_names]}) if run_names else None
	if not stage:
		return _not_available(student)
	run = frappe.db.get_value(
		_STUDENT_RUN_TYPE, stage["parent_run"], ["name", "student", "creation"], as_dict=True
	)
	return _stage_payload(stage, run)
