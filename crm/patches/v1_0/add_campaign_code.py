"""Backfill the stable, non-PII CRM Campaign code."""

import frappe

from crm.fcrm.campaign_code import campaign_code_year, next_campaign_code


def _code_exists(code: str, name: str) -> bool:
	return bool(frappe.db.exists("CRM Campaign", {"stable_code": code, "name": ["!=", name]}))


def _next_available_code(year: str, name: str) -> str:
	code = next_campaign_code(year)
	while _code_exists(code, name):
		code = next_campaign_code(year)
	return code


def execute():
	rows = frappe.db.sql(
		"""
		SELECT name, start_date, creation, stable_code
		FROM `tabCRM Campaign`
		WHERE stable_code IS NULL OR stable_code = ''
		ORDER BY creation ASC, name ASC
		""",
		as_dict=True,
	)
	for row in rows:
		year = campaign_code_year(
			row.get("start_date"), row.get("creation"), frappe.utils.now_datetime().year
		)
		code = _next_available_code(year, row.get("name"))
		frappe.db.set_value("CRM Campaign", row.get("name"), "stable_code", code, update_modified=False)
