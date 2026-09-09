"""Replace the temporary sequential CRM Segment codes with short IDs."""

import frappe

from crm.fcrm.segment_code import generate_segment_code, is_valid_segment_code, segment_code_date


def _next_unique_code(owner, creation, name):
	code = generate_segment_code(owner, segment_code_date(creation, frappe.utils.now_datetime()))
	while frappe.db.exists("CRM Segment", {"segment_code": code, "name": ["!=", name]}):
		code = generate_segment_code(owner, segment_code_date(creation, frappe.utils.now_datetime()))
	return code


def execute():
	rows = frappe.db.sql(
		"""
		SELECT name, owner, creation, segment_code
		FROM `tabCRM Segment`
		ORDER BY creation ASC, name ASC
		""",
		as_dict=True,
	)
	for row in rows:
		if is_valid_segment_code(row.get("segment_code")):
			continue
		code = _next_unique_code(row.get("owner") or "Administrator", row.get("creation"), row.get("name"))
		frappe.db.set_value("CRM Segment", row.get("name"), "segment_code", code, update_modified=False)
