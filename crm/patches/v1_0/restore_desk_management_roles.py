"""Restore Frappe Desk-management roles removed by a historical CRM patch."""

import frappe

from crm.fcrm.role_policy import DESK_MANAGEMENT_ROLE_NAMES, SYSTEM_MANAGER_ROLE
from crm.patches.v1_0.setup_crm_roles import create_roles


def execute():
	"""Provision Desk roles for every existing System Manager without touching other roles."""
	frappe.db.savepoint("restore_desk_management_roles")
	try:
		create_roles(DESK_MANAGEMENT_ROLE_NAMES)
		system_managers = frappe.get_all(
			"Has Role",
			filters={"role": SYSTEM_MANAGER_ROLE, "parenttype": "User"},
			pluck="parent",
		)
		for user in sorted(set(system_managers)):
			for role in DESK_MANAGEMENT_ROLE_NAMES:
				assignment = {
					"parent": user,
					"parenttype": "User",
					"parentfield": "roles",
					"role": role,
				}
				if not frappe.db.exists("Has Role", assignment):
					frappe.get_doc({"doctype": "Has Role", **assignment}).insert(ignore_permissions=True)
	except Exception:
		frappe.db.rollback(save_point="restore_desk_management_roles")
		raise
	frappe.clear_cache()
