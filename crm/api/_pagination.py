"""Shared start/page_length listing helper for simple CRUD-style APIs.

Centralizes the count-then-page pattern used by crm.api.action,
crm.api.action_type and crm.api.nba_read so each file doesn't reimplement
its own frappe.get_list(...)[0].total count query.
"""

import frappe


def parse_pagination(start=0, page_length=20, *, maximum=100, maximum_start=1_000_000):
	"""Validate and normalize the bounded pagination contract used by Admin APIs."""

	def parse(value, fieldname, default):
		value = default if value in (None, "") else value
		if isinstance(value, bool) or not str(value).strip().isdigit():
			frappe.throw(f"{fieldname} must be a non-negative integer.", frappe.ValidationError)
		return int(value)

	start = parse(start, "start", 0)
	page_length = parse(page_length, "page_length", 20)
	if start > maximum_start:
		frappe.throw(
			f"start must be between 0 and {maximum_start}.",
			frappe.ValidationError,
		)
	if page_length < 1 or page_length > maximum:
		frappe.throw(
			f"page_length must be between 1 and {maximum}.",
			frappe.ValidationError,
		)
	return start, page_length


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
	total_rows = frappe.get_list(
		doctype,
		filters=filters,
		or_filters=or_filters,
		limit_page_length=0,
		fields=["count(name) as total"],
	)
	total_row = total_rows[0] if total_rows else None
	total = total_row.get("total") if hasattr(total_row, "get") else getattr(total_row, "total", 0)

	return {"total": total, "start": start, "page_length": page_length, "rows": rows}
