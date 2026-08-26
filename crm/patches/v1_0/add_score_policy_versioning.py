"""Forward-only schema guard for score policy_revision/policy_hash.
Populates both fields on every existing CRM Score Template immediately,
instead of leaving them blank until the next unrelated edit happens to save
the doc."""

import frappe


def execute():
	for doctype in ("CRM Score Template", "CRM Score Signal"):
		frappe.reload_doc("fcrm", "doctype", frappe.scrub(doctype))

	for name in frappe.get_all("CRM Score Template", pluck="name"):
		frappe.get_doc("CRM Score Template", name).save(ignore_permissions=True)
