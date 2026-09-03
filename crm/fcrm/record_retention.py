"""Small, domain-neutral retention guards for technical CRM records."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping


TERMINAL_RECEIPT_OUTCOMES = frozenset({"attached", "created", "review_required", "review_applied", "applied", "rejected", "failed"})
TERMINAL_OUTBOX_STATUSES = frozenset({"delivered", "dead_letter", "quiesced", "cancelled"})


def eligible_for_retention(record: Mapping[str, object], *, kind: str, now: datetime) -> bool:
	"""Return whether a technical row may be retired without touching evidence.

	This is deliberately only an eligibility check. A migration or scheduled job
	must still perform the approved archival operation; this helper never deletes.
	"""
	if record.get("legal_hold") in (1, "1", True, "true", "True"):
		return False
	until = record.get("retention_until")
	if not isinstance(until, datetime) or until > now:
		return False
	if kind == "receipt":
		return record.get("outcome") in TERMINAL_RECEIPT_OUTCOMES
	if kind == "outbox":
		return record.get("status") in TERMINAL_OUTBOX_STATUSES
	return False


def redacted_identifier(value: object) -> str:
	"""Return a stable, non-identifying manifest token for an internal row."""
	import hashlib

	return hashlib.sha256(str(value).encode()).hexdigest()[:16]


def redacted_manifest(
	rows: list[Mapping[str, object]],
	*,
	identifier_field: str = "name",
	safe_fields: tuple[str, ...] = (),
) -> list[dict[str, object]]:
	"""Keep only a hashed row reference and explicitly allowlisted metadata."""
	return [
		{
			"record": redacted_identifier(row.get(identifier_field)),
			**{key: row.get(key) for key in safe_fields},
		}
		for row in rows
	]


def persist_private_artifact(*, filename: str, content: str) -> str:
	"""Persist a report as a private File, never as another business DocType."""
	import frappe

	doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"content": content,
			"is_private": 1,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _retention_days(kind: str) -> int:
	import frappe

	days = {
		"receipt": int(frappe.conf.get("crm_student_command_receipt_retention_days", 365)),
		"outbox": int(frappe.conf.get("crm_agent_event_retention_days", 90)),
		"analysis_run": int(frappe.conf.get("crm_analysis_run_retention_days", 400)),
	}.get(kind)
	if not days or days < 1:
		raise ValueError(f"Unsupported retention kind: {kind}")
	return days


def technical_retention_until(kind: str):
	"""Resolve server-owned technical-record retention, never client input."""
	from frappe.utils import add_to_date, now_datetime

	return add_to_date(now_datetime(), days=_retention_days(kind))


def technical_retention_cutoff(kind: str):
	"""Return the timestamp before which a record of ``kind`` is retention-expired."""
	from frappe.utils import add_to_date, now_datetime

	return add_to_date(now_datetime(), days=-_retention_days(kind))


def purge_expired_technical_records(*, approval_token: str, limit: int = 100) -> dict[str, int]:
	"""Explicit, approved cleanup for terminal infrastructure rows only.

	This function is deliberately not scheduled. Operators must configure a
	matching approval token after backup/retention sign-off before invoking it.
	"""
	import frappe
	from frappe.utils import now_datetime

	configured = frappe.conf.get("crm_technical_record_retention_approval")
	if not configured or approval_token != configured:
		raise frappe.PermissionError("A matching technical-record retention approval is required.")
	actor = getattr(frappe.session, "user", "Guest")
	if actor != "Administrator" and "System Manager" not in frappe.get_roles(actor):
		raise frappe.PermissionError("Only a System Manager may run technical-record retention.")
	now = now_datetime()
	deleted = {"receipt": 0, "outbox": 0}
	for doctype, kind, fields in (
		("CRM Student Command Receipt", "receipt", ["name", "outcome", "retention_until", "legal_hold"]),
		("CRM Agent Event", "outbox", ["name", "status", "retention_until", "legal_hold"]),
	):
		if not frappe.db.exists("DocType", doctype):
			continue
		candidates = frappe.get_all(doctype, fields=fields, order_by="retention_until asc", limit_page_length=min(max(int(limit), 1), 1000))
		names = [row.name for row in candidates if eligible_for_retention(row, kind=kind, now=now)]
		if names:
			frappe.db.delete(doctype, {"name": ["in", names]})
			deleted[kind] = len(names)
	return deleted
