"""Monotonic, append-only revision authority for School Intelligence."""
from __future__ import annotations

import frappe
from frappe.utils import now_datetime


def bump_school_intelligence_revision(high_school: str, reason: str, *, enqueue: bool = True) -> dict:
	"""Advance one school cursor after a material school-domain source mutation.

	A timestamp is deliberately not used as the run revision: independent child
	writes can reorder.  The counter is locked on the School aggregate instead.
	"""
	if not high_school:
		raise ValueError("high_school is required")
	row = frappe.db.sql(
		"SELECT intelligence_revision FROM `tabCRM High School` WHERE name = %s FOR UPDATE",
		(high_school,), as_dict=True,
	)
	if not row:
		raise frappe.DoesNotExistError(f"CRM High School {high_school} does not exist")
	revision = int(row[0].intelligence_revision or 0) + 1
	frappe.db.sql(
		"UPDATE `tabCRM High School` SET intelligence_revision = %s WHERE name = %s",
		(revision, high_school),
	)
	event_id = frappe.generate_hash(length=32)
	journal = frappe.get_doc({
		"doctype": "CRM School Intelligence Revision Journal",
		"event_id": event_id,
		"high_school": high_school,
		"revision": revision,
		"reason": str(reason or "material_change").strip()[:140] or "material_change",
		"actor": frappe.session.user,
		"occurred_at": now_datetime(),
		"idempotency_key": event_id,
	}).insert(ignore_permissions=True)
	from crm.fcrm.intelligence_runs import request_automatic_run, unified_intelligence_enabled
	if enqueue and unified_intelligence_enabled():
		request_automatic_run("school", high_school)
	return {"high_school": high_school, "revision": revision, "journal": journal.name}


def mark_school_intelligence_changed(doc, method=None) -> dict | None:
	"""Frappe document hook for bounded School-360 source types only."""
	high_school = doc.get("high_school")
	if not high_school:
		return None
	reason = {
		"CRM High School Annual Snapshot": "verified_snapshot_changed",
		"CRM School Stakeholder": "stakeholder_changed",
		"CRM School Activity": "activity_or_outcome_changed",
	}.get(doc.doctype)
	if not reason:
		return None
	if doc.doctype == "CRM High School Annual Snapshot" and doc.get("verification_status") != "Verified":
		return None
	return bump_school_intelligence_revision(high_school, reason)
