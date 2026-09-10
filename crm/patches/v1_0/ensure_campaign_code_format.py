"""Backfill missing Campaign codes using the current Campus/date format."""

import frappe

from crm.fcrm.campaign_code import (
	campaign_code_date,
	next_campaign_code,
	normalize_campus_code,
)


def _code_exists(code: str, name: str) -> bool:
	return bool(frappe.db.exists("CRM Campaign", {"stable_code": code, "name": ["!=", name]}))


def _next_available_code(campus_code: str, code_date: str, name: str) -> str:
	code = next_campaign_code(campus_code, code_date)
	while _code_exists(code, name):
		code = next_campaign_code(campus_code, code_date)
	return code


def execute():
	rows = frappe.db.sql(
		"""
		SELECT name, campus, creation
		FROM `tabCRM Campaign`
		WHERE stable_code IS NULL OR stable_code = ''
		ORDER BY creation ASC, name ASC
		""",
		as_dict=True,
	)
	pending = []
	failures = []
	for row in rows:
		campus_code = frappe.db.get_value("CRM Campus", row.get("campus"), "campus_code")
		if not campus_code:
			failures.append(f"{row.get('name')}: Campus Code is required.")
			continue
		try:
			normalized_campus_code = normalize_campus_code(campus_code)
		except ValueError as error:
			failures.append(f"{row.get('name')}: {error}")
			continue
		code_date = campaign_code_date(row.get("creation"), frappe.utils.now_datetime())
		pending.append((row.get("name"), normalized_campus_code, code_date))

	if failures:
		frappe.throw(
			"Campaign code backfill failed; fix Campus Code first: " + "; ".join(failures),
			frappe.ValidationError,
		)

	for name, campus_code, code_date in pending:
		code = _next_available_code(campus_code, code_date, name)
		frappe.db.set_value("CRM Campaign", name, "stable_code", code, update_modified=False)
