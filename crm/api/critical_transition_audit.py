"""Whitelisted, flag-gated entry point for the Phase 9 audit read model."""

from __future__ import annotations

import frappe

from crm.fcrm.critical_transition_audit import critical_transition_timeline
from crm.fcrm.governance_audit_flags import enabled


def _actor() -> str:
	actor = getattr(getattr(frappe, "session", None), "user", None)
	if not actor or actor in {"Guest", "None"}:
		frappe.throw("Authentication is required.", frappe.PermissionError)
	return actor


@frappe.whitelist()
def get_critical_transition_timeline(student: str, limit: int = 20, cursor: str | None = None):
	_actor()
	if not enabled("audit_read"):
		return {"student": student, "timeline": [], "next_cursor": None, "read_enabled": False}
	return {**critical_transition_timeline(student, limit=limit, cursor=cursor), "read_enabled": True}
