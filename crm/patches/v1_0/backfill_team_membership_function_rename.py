"""
Backfill CRM Team Membership.function values written under the old
"Lead Sales" label before the canonical role rename to "Lead Sale"
(migrate_to_canonical_crm_roles). This field is a plain Select, not a Link to
Role, so the role-rename patch never touched it.
"""

import frappe


def execute():
	if not frappe.db.table_exists("CRM Team Membership"):
		return
	frappe.db.sql(
		"UPDATE `tabCRM Team Membership` SET function = %s WHERE function = %s",
		("Lead Sale", "Lead Sales"),
	)
