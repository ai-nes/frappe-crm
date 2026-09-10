"""Align Lead codes with the year, region, and sequence of HS Student codes."""

import frappe

from crm.fcrm.lead_code import lead_code_from_name, lead_code_year, next_lead_code


def _code_exists(code: str, name: str) -> bool:
	return bool(frappe.db.exists("CRM Lead", {"lead_code": code, "name": ["!=", name]}))


def execute():
	rows = frappe.db.sql(
		"""
		SELECT name, admission_year, creation
		FROM `tabCRM Lead`
		ORDER BY creation ASC, name ASC
		""",
		as_dict=True,
	)
	for row in rows:
		code = lead_code_from_name(row.get("name"))
		if not code or _code_exists(code, row["name"]):
			year = lead_code_year(
				row.get("admission_year"), row.get("creation"), frappe.utils.now_datetime().year
			)
			code = next_lead_code(year)
			while _code_exists(code, row["name"]):
				code = next_lead_code(year)
		if not _code_exists(code, row["name"]):
			frappe.db.set_value("CRM Lead", row["name"], "lead_code", code, update_modified=False)
