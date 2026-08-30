"""Admin-only parity report adapter for admissions read-model cutover."""

from __future__ import annotations

import json

import frappe

from crm.fcrm.admissions_reconciliation import build_reconciliation_report


def _require_admin():
	if frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles(frappe.session.user):
		return
	frappe.throw("Only an administrator may run admissions reconciliation.", frappe.PermissionError)


@frappe.whitelist()
def reconcile(cohorts):
	_require_admin()
	if isinstance(cohorts, str):
		cohorts = json.loads(cohorts)
	if not isinstance(cohorts, list):
		frappe.throw("Cohorts must be a list.", frappe.ValidationError)
	return build_reconciliation_report(cohorts)
