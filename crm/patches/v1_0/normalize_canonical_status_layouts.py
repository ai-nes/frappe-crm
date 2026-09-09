"""Normalize canonical Lead/Student status fields in saved layouts."""

from __future__ import annotations

import frappe

CANONICAL_FIELDS = {
	"CRM Lead": ("processing_status", "resolution"),
	"CRM Student": ("student_stage",),
}
REMOVED_FIELDS = {"lead_status", "conversion_status", "enrollment_status", "lifecycle_stage"}


def _clean_layout(value, canonical_fields: tuple[str, ...]):
	field_lists: list[tuple[int, list[str]]] = []

	def visit(node):
		if isinstance(node, dict):
			fields = node.get("fields")
			if isinstance(fields, list):
				cleaned = [
					field
					for field in fields
					if field not in REMOVED_FIELDS and field not in canonical_fields
				]
				node["fields"] = cleaned
				priority = 0 if node.get("name") in {"col_status", "col_stage"} else 1
				field_lists.append((priority, cleaned))
			for child in node.values():
				visit(child)
		elif isinstance(node, list):
			for child in node:
				visit(child)

	visit(value)
	if not field_lists:
		return value
	_, target = min(field_lists, key=lambda item: item[0])
	target.extend(canonical_fields)
	return value


def execute() -> None:
	if not frappe.db.table_exists("Fields Layout"):
		return
	for row in frappe.db.get_all(
		"Fields Layout",
		filters={"dt": ["in", list(CANONICAL_FIELDS)]},
		fields=["name", "dt", "layout"],
		limit_page_length=0,
	):
		if not row.get("layout"):
			continue
		try:
			layout = frappe.parse_json(row.layout)
		except (TypeError, ValueError):
			continue
		cleaned = _clean_layout(layout, CANONICAL_FIELDS[row.dt])
		frappe.db.set_value(
			"Fields Layout",
			row.name,
			"layout",
			frappe.as_json(cleaned),
			update_modified=False,
		)
