"""Create governed Lead Sources for canonical Campaign Channel Types."""

import frappe

from crm.fcrm.campaign_channel_type_catalog import CAMPAIGN_CHANNEL_TYPE_CATALOG


def _insert_if_missing(display_name: str, modes: tuple[str, ...]) -> None:
	if frappe.db.exists("CRM Lead Source", {"source_name": display_name}):
		return
	frappe.get_doc(
		{
			"doctype": "CRM Lead Source",
			"source_name": display_name,
			"is_digital": int("ONLINE" in modes),
		}
	).insert(ignore_permissions=True)


def execute():
	"""Seed one Lead Source per canonical Campaign Channel Type."""
	# Migrations are the controlled additive boundary for existing sites.  Keep
	# the hook bypass scoped to this patch; interactive writes still require the
	# master-data governance command.
	previous_flag = frappe.flags.get("crm_governance_additive")
	frappe.flags.crm_governance_additive = True
	try:
		for _code, display_name, modes in CAMPAIGN_CHANNEL_TYPE_CATALOG:
			_insert_if_missing(display_name, modes)
	finally:
		frappe.flags.crm_governance_additive = previous_flag

	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()
