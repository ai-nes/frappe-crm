"""Whitelisted Student 360 assessment commands and context read endpoint."""

from __future__ import annotations

import json
from typing import Any

import frappe

from crm.fcrm.student_assessment import (
	confirm_student_assessment as _confirm_student_assessment,
	get_student_assessment_context as _get_student_assessment_context,
	record_student_assessment as _record_student_assessment,
)


def _json(value: Any, default: Any = None):
	if isinstance(value, str):
		try:
			return json.loads(value)
		except (TypeError, ValueError):
			return default if default is not None else value
	return value if value is not None else default


@frappe.whitelist(methods=["POST"])
def record_assessment(
	student: str,
	interest: str,
	fit: str,
	primary_barrier: str,
	interest_confidence: float = 0,
	fit_confidence: float = 0,
	barrier_confidence: float = 0,
	source: str = "system",
	reason: str | None = None,
	evidence_references: Any = None,
	policy_version: str | None = None,
	model_version: str | None = None,
) -> dict:
	return _record_student_assessment(
		student,
		{
			"interest": interest,
			"fit": fit,
			"primary_barrier": primary_barrier,
			"interest_confidence": interest_confidence,
			"fit_confidence": fit_confidence,
			"barrier_confidence": barrier_confidence,
		},
		source=source,
		reason=reason or "",
		evidence_references=_json(evidence_references, []),
		policy_version=policy_version or "student-360-assessment-v1",
		model_version=model_version,
	)


@frappe.whitelist(methods=["POST"])
def confirm_assessment(
	name: str,
	override: dict[str, Any] | str | None = None,
	reason: str | None = None,
) -> dict:
	return _confirm_student_assessment(name, override=_json(override, {}) or {}, reason=reason)


@frappe.whitelist()
def get_assessment_context(student: str) -> dict:
	return _get_student_assessment_context(student)
