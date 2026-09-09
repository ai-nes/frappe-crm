"""Backfill the stable CRM Segment code for existing records."""

import frappe

from crm.fcrm.segment_code import generate_segment_code, segment_code_date


def execute():
	rows = frappe.db.sql(
		"""
		SELECT name, owner, creation, segment_code
		FROM `tabCRM Segment`
		WHERE segment_code IS NULL OR segment_code = ''
		ORDER BY creation ASC, name ASC
		""",
		as_dict=True,
	)
	for row in rows:
		code = generate_segment_code(
			row.get("owner") or "Administrator",
			segment_code_date(row.get("creation"), frappe.utils.now_datetime()),
		)
		frappe.db.set_value("CRM Segment", row.get("name"), "segment_code", code, update_modified=False)
