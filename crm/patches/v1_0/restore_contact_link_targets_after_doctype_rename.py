"""Restore links to the post-conversion CRM Student DocType after renaming."""

import frappe

CONTACT_LINK_FIELDS = (
	("CRM Action Item", "contact"),
	("CRM AI Lead Insight", "contact"),
	("CRM AI Personal Email Draft", "contact"),
)


def execute():
	if not frappe.db.exists("DocType", "CRM Student"):
		return

	for parent, fieldname in CONTACT_LINK_FIELDS:
		if not frappe.db.exists("DocField", {"parent": parent, "fieldname": fieldname}):
			continue
		frappe.db.set_value(
			"DocField",
			{"parent": parent, "fieldname": fieldname},
			"options",
			"CRM Student",
			update_modified=False,
		)

	frappe.clear_cache()
