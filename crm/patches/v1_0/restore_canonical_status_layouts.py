"""Ensure standard Lead/Student layouts expose only canonical status fields."""

from __future__ import annotations

import frappe

from crm.patches.v1_0.drop_redundant_lead_student_status_fields import _without_removed_fields

CANONICAL_FIELDS = {
	"CRM Lead": ("processing_status", "resolution"),
	"CRM Student": ("student_stage",),
}


def _field_lists(value):
	if isinstance(value, dict):
		fields = value.get("fields")
		if isinstance(fields, list):
			priority = 0 if value.get("name") in {"col_status", "col_stage"} else 1
			yield priority, fields
		for key, item in value.items():
			if key != "fields":
				yield from _field_lists(item)
	elif isinstance(value, list):
		for item in value:
			yield from _field_lists(item)


def execute() -> None:
	if not frappe.db.table_exists("Fields Layout"):
		return
	removed = {"lead_status", "conversion_status", "enrollment_status", "lifecycle_stage"}
	rows = frappe.db.get_all(
		"Fields Layout",
		filters={"dt": ["in", list(CANONICAL_FIELDS)]},
		fields=["name", "dt", "layout"],
		limit_page_length=0,
	)
	for row in rows:
		if not row.get("layout"):
			continue
		try:
			layout = frappe.parse_json(row.layout)
		except (TypeError, ValueError):
			continue
		cleaned = _without_removed_fields(layout, removed)
		field_lists = list(_field_lists(cleaned))
		if field_lists:
			_, target = min(field_lists, key=lambda item: item[0])
			for field in CANONICAL_FIELDS[row.dt]:
				if field not in target:
					target.append(field)
		updated = cleaned != layout
		if field_lists and any(field in target for field in CANONICAL_FIELDS[row.dt]):
			updated = updated or any(
				field in fields
				for _, fields in field_lists
				if fields is not target
				for field in CANONICAL_FIELDS[row.dt]
			)
		if updated:
			frappe.db.set_value(
				"Fields Layout",
				row.name,
				"layout",
				frappe.as_json(cleaned),
				update_modified=False,
			)
