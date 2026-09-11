"""Move admin-managed templates into the dedicated library DocType."""

import frappe

from crm.patches.v1_0.seed_crm_message_templates import SYSTEM_TEMPLATES


def execute():
	legacy_rows = frappe.get_all(
		"CRM Message Template",
		filters={"is_system_template": 1},
		fields=[
			"name",
			"template_name",
			"library_category",
			"description",
			"subject",
			"body",
			"owner",
		],
		limit_page_length=0,
	)
	rows = legacy_rows or [frappe._dict(template) for template in SYSTEM_TEMPLATES]

	for row in rows:
		if frappe.db.exists("CRM Message Template Library", {"template_name": row.template_name}):
			continue
		frappe.get_doc(
			{
				"doctype": "CRM Message Template Library",
				"naming_series": "MSG-LIB-.###",
				"owner": row.get("owner") or "Administrator",
				"template_name": row.template_name,
				"category": row.get("library_category") or row.get("category") or "general",
				"description": row.get("description") or "",
				"subject": row.subject,
				"body": row.body,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

	for row in legacy_rows:
		frappe.delete_doc(
			"CRM Message Template",
			row.name,
			force=True,
			ignore_permissions=True,
		)
