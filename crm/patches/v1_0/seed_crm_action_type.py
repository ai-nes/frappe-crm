"""Seed the canonical CRM Action Type and CRM Action master data."""

import json

import frappe

from crm.fcrm.action_type_catalog import ACTION_TYPE_CATALOG

CATEGORY_LABELS = {
	"CONTACT": "Contact",
	"INFORMATION": "Information",
	"ENGAGEMENT": "Engagement",
	"APPLICATION": "Application",
	"CONVERSION": "Conversion",
	"PARENT": "Parent",
	"RECOVERY": "Recovery",
	"INTERNAL": "Internal",
}

DEFAULT_ACTORS = ["Sale", "Lead Sales", "Admissions Director"]


def _insert_if_missing(doctype, name, values):
	if frappe.db.exists(doctype, name):
		return
	frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)


def execute():
	"""Create missing categories and all 79 canonical actions idempotently."""
	for sort_order, category in enumerate(CATEGORY_LABELS, start=1):
		_insert_if_missing(
			"CRM Action Type",
			category,
			{
				"action_type": category,
				"display_name": CATEGORY_LABELS[category],
				"enabled": 1,
				"sort_order": sort_order * 10,
			},
		)

	for sort_order, (code, display_name, category) in enumerate(ACTION_TYPE_CATALOG, start=1):
		_insert_if_missing(
			"CRM Action",
			code,
			{
				"code": code,
				"display_name": display_name,
				"action_type": category,
				"description": f"Canonical CRM action: {display_name}.",
				"purpose": f"Execute the {display_name.lower()} action.",
				"default_channel": "NONE",
				"allowed_actors": json.dumps(DEFAULT_ACTORS),
				"requires_approval": 0,
				"auto_execute": 0,
				"enabled": 1,
				"sort_order": sort_order * 10,
			},
		)

	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()
