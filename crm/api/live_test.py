"""Explicitly guarded credentials for local Docker live tests.

This is the replacement for the removed ``crm.demo.seed_e2e`` module.  It is
never enabled on a non-local site and mints only for the already authenticated
current session; callers cannot select another user or receive service keys.
"""
from __future__ import annotations

import frappe


@frappe.whitelist()
def issue_current_delegated_credential() -> dict[str, str]:
	if getattr(frappe.local, "site", None) != "crm.localhost" or not frappe.conf.get("e2e_live_test_enabled"):
		frappe.throw("Local live-test credentials are disabled.", frappe.PermissionError)
	if frappe.session.user in ("", "Guest") or not frappe.session.sid:
		frappe.throw("Authentication is required.", frappe.PermissionError)
	from crm.api.copilot_delegation import mint_delegated_credential

	return mint_delegated_credential()
