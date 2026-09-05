"""System-manager-only dry-run endpoint for Interaction cutover evidence."""

from __future__ import annotations

import json

import frappe
from frappe import _

from crm.fcrm.interaction_cutover import dry_run_report


def _require_operator() -> None:
	if "System Manager" not in frappe.get_roles(frappe.session.user):
		frappe.throw(_("Only a System Manager may inspect interaction cutover readiness."), frappe.PermissionError)


@frappe.whitelist()
def dry_run(manifest=None, metrics=None, thresholds=None):
	"""Return aggregate readiness only. This endpoint performs no cutover write."""
	_require_operator()
	def parse(value):
		return json.loads(value) if isinstance(value, str) else value
	return dry_run_report(parse(manifest), parse(metrics), parse(thresholds))
