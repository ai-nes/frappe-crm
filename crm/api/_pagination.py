"""Shared start/page_length listing helper for simple CRUD-style APIs.

Centralizes the count-then-page pattern used by crm.api.action,
crm.api.action_type and crm.api.nba_read so each file doesn't reimplement
its own frappe.get_list(...)[0].total count query.
"""

import frappe


def paged_list(doctype, fields, filters=None, or_filters=None, start=0, page_length=20, order_by=None):
	start = frappe.utils.cint(start)
	page_length = frappe.utils.cint(page_length) or 20
	filters = filters or {}

	rows = frappe.get_list(
		doctype,
		fields=fields,
		filters=filters,
		or_filters=or_filters,
		start=start,
		page_length=page_length,
		order_by=order_by,
	)
	total = frappe.get_list(
		doctype,
		filters=filters,
		or_filters=or_filters,
		limit_page_length=0,
		fields=["count(name) as total"],
	)[0].total

	return {"total": total, "start": start, "page_length": page_length, "rows": rows}
