"""Projection writer for Student Engagement Event."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import frappe
from frappe import _

from crm.fcrm.admissions_migration import stable_fingerprint


@contextmanager
def _projection_context():
	previous = getattr(frappe.flags, "student_engagement_projection_writer", False)
	frappe.flags.student_engagement_projection_writer = True
	try:
		yield
	finally:
		frappe.flags.student_engagement_projection_writer = previous


def project_student_engagement_event(
	*,
	student: str,
	event_type: str,
	occurred_at: str,
	source_doctype: str,
	source_name: str,
	source_reference: str | None = None,
	values: dict[str, Any] | None = None,
) -> dict[str, Any]:
	if not all(str(value or "").strip() for value in (student, event_type, occurred_at, source_doctype, source_name)):
		frappe.throw(_("Student engagement source and event grain are required."), frappe.ValidationError)
	fingerprint = stable_fingerprint(source_doctype, source_name, student, event_type)
	existing = frappe.db.get_value("CRM Student Engagement Event", {"idempotency_fingerprint": fingerprint}, "name")
	if existing:
		return {"event": existing, "replayed": True}
	data = {
		"doctype": "CRM Student Engagement Event",
		**(values or {}),
		"student": student,
		"event_type": event_type,
		"occurred_at": occurred_at,
		"source_doctype": source_doctype,
		"source_name": source_name,
		"source_reference": source_reference or f"{source_doctype}:{source_name}",
		"idempotency_fingerprint": fingerprint,
		"consent_state": "Unknown",
	}
	with _projection_context():
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
	return {"event": doc.name, "replayed": False}
