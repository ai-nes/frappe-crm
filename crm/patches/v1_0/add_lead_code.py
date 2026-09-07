"""Add and backfill the stable, non-PII CRM Lead code."""

import frappe

from crm.fcrm.lead_code import lead_code_from_name, lead_code_year, next_lead_code


def _code_exists(code: str, name: str) -> bool:
	return bool(frappe.db.exists("CRM Lead", {"lead_code": code, "name": ["!=", name]}))


def _next_available_code(year: str, name: str) -> str:
	code = next_lead_code(year)
	while _code_exists(code, name):
		code = next_lead_code(year)
	return code


def execute():
	rows = frappe.db.sql(
		"""
		SELECT name, admission_year, creation, lead_code
		FROM `tabCRM Lead`
		WHERE lead_code IS NULL OR lead_code = ''
		ORDER BY creation ASC, name ASC
		""",
		as_dict=True,
	)
	for row in rows:
		code = lead_code_from_name(row.get("name"))
		year = lead_code_year(
			row.get("admission_year"), row.get("creation"), frappe.utils.now_datetime().year
		)
		if not code or _code_exists(code, row.get("name")):
			code = _next_available_code(year, row.get("name"))
		frappe.db.set_value("CRM Lead", row.get("name"), "lead_code", code, update_modified=False)
