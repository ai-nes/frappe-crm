"""Install the school-domain role, governed terms and new DocTypes."""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.exists("Role", "Promoter"):
		frappe.get_doc({"doctype": "Role", "role_name": "Promoter", "desk_access": 1}).insert(ignore_permissions=True)
	for doctype in (
		"crm_high_school",
		"crm_person",
		"crm_school_stakeholder",
		"crm_high_school_annual_snapshot",
		"crm_school_activity",
	):
		frappe.reload_doc("fcrm", "doctype", doctype, force=True)
	frappe.clear_cache()
