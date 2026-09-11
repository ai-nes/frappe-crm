"""Student 360 assessment command and read-model services."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from crm.fcrm.doctype.crm_student_assessment.crm_student_assessment import (
	ASSESSMENT_SOURCES,
	BARRIERS,
	LEVELS,
	parse_evidence,
)
from crm.fcrm.student_reference import canonical_student
from crm.services.student_context import mark_student_context_changed

ASSESSMENT_POLICY_VERSION = "student-360-assessment-v1"


def _student_for_write(student: str):
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	canonical = canonical_student(student)
	if not canonical:
		frappe.throw(_("A canonical CRM Student is required for assessment."), frappe.ValidationError)
	doc = frappe.get_doc("CRM Student", canonical)
	if not doc.has_permission("write"):
		frappe.throw(_("You do not have permission to assess this Student."), frappe.PermissionError)
	actor = frappe.session.user
	roles = set(frappe.get_roles(actor))
	if actor != "Administrator" and not ({"System Manager", "Admissions Director"} & roles):
		if not frappe.has_permission("CRM Student Assessment", "create", user=actor):
			frappe.throw(
				_("You do not have permission to write Student assessments."), frappe.PermissionError
			)
	return doc


def _current(student: str, statuses=("confirmed", "proposed")):
	return frappe.db.get_value(
		"CRM Student Assessment",
		{"student": student, "status": ["in", list(statuses)]},
		[
			"name",
			"student",
			"assessment_revision",
			"status",
			"assessment_source",
			"assessed_at",
			"policy_version",
			"model_version",
			"interest",
			"interest_confidence",
			"fit",
			"fit_confidence",
			"primary_barrier",
			"barrier_confidence",
			"reason",
			"evidence_references",
			"supersedes",
			"confirmed_by",
			"confirmed_at",
			"override_reason",
		],
		order_by="assessment_revision desc, creation desc",
		as_dict=True,
	)


def _next_revision(student: str) -> int:
	# Serialize revision allocation against the Student row so concurrent
	# commands cannot observe the same max revision.
	frappe.db.sql("SELECT name FROM `tabCRM Student` WHERE name = %s FOR UPDATE", (student,))
	return (
		int(
			frappe.db.get_value("CRM Student Assessment", {"student": student}, "max(assessment_revision)")
			or 0
		)
		+ 1
	)


def _decode(value: Any):
	if isinstance(value, str):
		try:
			return json.loads(value)
		except (TypeError, ValueError):
			return value
	return value


def _validate_values(values: dict[str, Any]) -> dict[str, Any]:
	data = {
		"interest": str(values.get("interest") or "Unknown"),
		"fit": str(values.get("fit") or "Unknown"),
		"primary_barrier": str(values.get("primary_barrier") or "Unknown"),
		"interest_confidence": float(values.get("interest_confidence") or 0),
		"fit_confidence": float(values.get("fit_confidence") or 0),
		"barrier_confidence": float(values.get("barrier_confidence") or 0),
		"enrollment_probability": float(values.get("enrollment_probability") or 0),
	}
	if data["interest"] not in LEVELS or data["fit"] not in LEVELS:
		frappe.throw(_("Interest and Fit must be High, Medium, Low, or Unknown."), frappe.ValidationError)
	if data["primary_barrier"] not in BARRIERS:
		frappe.throw(_("Primary Barrier is invalid."), frappe.ValidationError)
	for key in (
		"interest_confidence",
		"fit_confidence",
		"barrier_confidence",
		"enrollment_probability",
	):
		if not 0 <= data[key] <= 100:
			frappe.throw(_("{0} must be between 0 and 100.").format(key), frappe.ValidationError)
	return data


def _project(student: str, assessment) -> None:
	values = {
		"assessment_status": assessment.status,
		"assessment_revision": assessment.assessment_revision,
		"interest_level": assessment.interest,
		"fit_level": assessment.fit,
		"primary_barrier": assessment.primary_barrier,
	}
	frappe.db.set_value("CRM Student", student, values, update_modified=False)
	mark_student_context_changed(student, "student_360_assessment_changed")


def _supersede_current(student: str, exclude: str | None = None) -> None:
	rows = frappe.get_all(
		"CRM Student Assessment",
		filters={"student": student, "status": ["in", ["confirmed", "proposed"]]},
		fields=["name"],
		order_by="assessment_revision desc",
	)
	for row in rows:
		if row.name == exclude:
			continue
		doc = frappe.get_doc("CRM Student Assessment", row.name)
		doc.flags.student_assessment_command = True
		doc.status = "superseded"
		doc.save(ignore_permissions=True)


def record_student_assessment(
	student: str,
	values: dict[str, Any],
	*,
	source: str,
	reason: str,
	evidence_references: Any,
	policy_version: str = ASSESSMENT_POLICY_VERSION,
	model_version: str | None = None,
	confirm: bool = False,
) -> dict[str, Any]:
	student_doc = _student_for_write(student)
	source = str(source or "").strip().lower()
	if source not in ASSESSMENT_SOURCES:
		frappe.throw(_("Assessment source must be system or manual."), frappe.ValidationError)
	if source == "system":
		actor = getattr(frappe.session, "user", None)
		roles = set(frappe.get_roles(actor))
		configured_service_user = frappe.conf.get("crm_student_assessment_system_user")
		if not (
			getattr(frappe.flags, "student_assessment_system_service", False)
			or actor == "Administrator"
			or "System Manager" in roles
			or (configured_service_user and actor == configured_service_user)
		):
			frappe.throw(
				_("System assessments must be submitted by the configured assessment service."),
				frappe.PermissionError,
			)
	if source == "system" and confirm:
		frappe.throw(
			_("System assessments require human confirmation before becoming current."),
			frappe.ValidationError,
		)
	reason = str(reason or "").strip()
	if not reason:
		frappe.throw(_("An explainable assessment reason is required."), frappe.ValidationError)
	evidence = parse_evidence(_decode(evidence_references))
	if not evidence:
		frappe.throw(_("At least one assessment evidence reference is required."), frappe.ValidationError)
	data = _validate_values(values)
	now = now_datetime()
	prior = _current(student_doc.name, ("confirmed", "proposed"))
	doc = frappe.get_doc(
		{
			"doctype": "CRM Student Assessment",
			"student": student_doc.name,
			"crm_student": canonical_student(student_doc.name),
			"assessment_revision": _next_revision(student_doc.name),
			"status": "confirmed" if confirm or source == "manual" else "proposed",
			"assessment_source": source,
			"assessed_at": now,
			"policy_version": policy_version or ASSESSMENT_POLICY_VERSION,
			"model_version": model_version,
			"supersedes": prior.get("name") if prior else None,
			**data,
			"reason": reason[:2000],
			"evidence_references": evidence,
			"confirmed_by": frappe.session.user if (confirm or source == "manual") else None,
			"confirmed_at": now if (confirm or source == "manual") else None,
		}
	)
	doc.flags.student_assessment_command = True
	doc.insert(ignore_permissions=True)
	if doc.status == "confirmed":
		_supersede_current(student_doc.name, exclude=doc.name)
		_project(student_doc.name, doc)
	return serialize_assessment(doc)


def confirm_student_assessment(
	name: str, *, override: dict[str, Any] | None = None, reason: str | None = None
) -> dict[str, Any]:
	doc = frappe.get_doc("CRM Student Assessment", name)
	_student_for_write(doc.student)
	if doc.status != "proposed":
		frappe.throw(_("Only a proposed assessment can be confirmed."), frappe.ValidationError)
	override = override or {}
	override_changed = False
	if override:
		for key in (
			"interest",
			"fit",
			"primary_barrier",
			"interest_confidence",
			"fit_confidence",
			"barrier_confidence",
		):
			if key in override and str(override.get(key)) != str(doc.get(key)):
				override_changed = True
		data = _validate_values(
			{
				"interest": override.get("interest", doc.interest),
				"fit": override.get("fit", doc.fit),
				"primary_barrier": override.get("primary_barrier", doc.primary_barrier),
				"interest_confidence": override.get("interest_confidence", doc.interest_confidence),
				"fit_confidence": override.get("fit_confidence", doc.fit_confidence),
				"barrier_confidence": override.get("barrier_confidence", doc.barrier_confidence),
			}
		)
		for key, value in data.items():
			setattr(doc, key, value)
		if reason:
			doc.reason = str(reason).strip()[:2000]
	if not str(doc.reason or "").strip():
		frappe.throw(_("A confirmation reason is required."), frappe.ValidationError)
	doc.status = "confirmed"
	doc.confirmed_by = frappe.session.user
	doc.confirmed_at = now_datetime()
	doc.override_reason = (
		(str(reason or "").strip()[:2000] or None) if override_changed else doc.override_reason
	)
	doc.flags.student_assessment_command = True
	doc.save(ignore_permissions=True)
	_supersede_current(doc.student, exclude=doc.name)
	_project(doc.student, doc)
	return serialize_assessment(doc)


def serialize_assessment(doc) -> dict[str, Any]:
	return {
		"name": doc.name,
		"student": doc.student,
		"revision": int(doc.assessment_revision or 0),
		"status": doc.status,
		"source": doc.assessment_source,
		"assessed_at": str(doc.assessed_at) if doc.assessed_at else None,
		"policy_version": doc.policy_version,
		"model_version": doc.model_version,
		"interest": doc.interest,
		"interest_confidence": doc.interest_confidence,
		"fit": doc.fit,
		"fit_confidence": doc.fit_confidence,
		"primary_barrier": doc.primary_barrier,
		"barrier_confidence": doc.barrier_confidence,
		"enrollment_probability": doc.enrollment_probability,
		"reason": doc.reason,
		"evidence_references": parse_evidence(doc.evidence_references),
		"supersedes": doc.supersedes,
		"confirmed_by": doc.confirmed_by,
		"confirmed_at": str(doc.confirmed_at) if doc.confirmed_at else None,
		"override_reason": doc.override_reason,
	}


def get_student_assessment_context(student: str) -> dict[str, Any]:
	canonical = canonical_student(student)
	if not canonical:
		frappe.throw(_("A canonical CRM Student is required for assessment."), frappe.ValidationError)
	doc = frappe.get_doc("CRM Student", canonical)
	if not doc.has_permission("read"):
		frappe.throw(_("You do not have permission to view this Student."), frappe.PermissionError)
	current = _current(student, ("confirmed",))
	pending = _current(student, ("proposed",))
	history = frappe.get_all(
		"CRM Student Assessment",
		filters={"student": student},
		fields=["name"],
		order_by="assessment_revision desc",
		limit_page_length=20,
	)
	return {
		"current": serialize_assessment(frappe.get_doc("CRM Student Assessment", current.name))
		if current
		else None,
		"pending": serialize_assessment(frappe.get_doc("CRM Student Assessment", pending.name))
		if pending
		else None,
		"history": [
			serialize_assessment(frappe.get_doc("CRM Student Assessment", row.name)) for row in history
		],
		"student_context_revision": int(doc.get("student_context_revision") or 0),
		"policy_version": ASSESSMENT_POLICY_VERSION,
	}
