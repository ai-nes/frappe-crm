"""Seed the canonical campaign channel type lookup."""

import frappe

from crm.fcrm.campaign_channel_type_catalog import CAMPAIGN_CHANNEL_TYPE_CATALOG


def _insert_if_missing(code: str, display_name: str, modes: tuple[str, ...], sort_order: int) -> None:
	if frappe.db.exists("CRM Campaign Channel Type", code):
		return
	frappe.get_doc(
		{
			"doctype": "CRM Campaign Channel Type",
			"code": code,
			"display_name": display_name,
			"is_online": int("ONLINE" in modes),
			"is_offline": int("OFFLINE" in modes),
			"enabled": 1,
			"sort_order": sort_order * 10,
			"description": f"Canonical campaign channel type: {display_name}.",
		}
	).insert(ignore_permissions=True)


def execute():
	"""Create all 24 canonical campaign channel types idempotently."""
	for sort_order, (code, display_name, modes) in enumerate(CAMPAIGN_CHANNEL_TYPE_CATALOG, start=1):
		_insert_if_missing(code, display_name, modes, sort_order)

	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()
