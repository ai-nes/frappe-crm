"""Give CRM Leads their own public code namespace instead of reusing HS IDs."""

import frappe

from crm.fcrm.lead_code import lead_code_year, next_lead_code


def execute():
	rows = frappe.db.sql(
		"""
		SELECT name, admission_year, creation, lead_code
		FROM `tabCRM Lead`
		ORDER BY creation ASC, name ASC
		""",
		as_dict=True,
	)
	for row in rows:
		current = str(row.get("lead_code") or "")
		if current.startswith("LD-"):
			continue
		year = lead_code_year(
			row.get("admission_year"), row.get("creation"), frappe.utils.now_datetime().year
		)
		code = next_lead_code(year)
		while frappe.db.exists("CRM Lead", {"lead_code": code, "name": ["!=", row["name"]]}):
			code = next_lead_code(year)
		frappe.db.set_value("CRM Lead", row["name"], "lead_code", code, update_modified=False)
