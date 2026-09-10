import json

import frappe


def execute():
	if not frappe.db.exists("Fields Layout", "CRM Lead-Quick Entry"):
		return

	layout_doc = frappe.get_doc("Fields Layout", "CRM Lead-Quick Entry")
	if not layout_doc.layout:
		return

	try:
		parsed = json.loads(layout_doc.layout)
	except (json.JSONDecodeError, TypeError):
		return

	dirty = False

	def replace_in_columns(columns):
		nonlocal dirty
		for column in columns:
			fields = column.get("fields", [])
			if "mobile_no" in fields:
				column["fields"] = ["phone" if f == "mobile_no" else f for f in fields]
				dirty = True

	for entry in parsed:
		if "columns" in entry:
			replace_in_columns(entry.get("columns", []))
		for section in entry.get("sections", []):
			replace_in_columns(section.get("columns", []))

	if dirty:
		frappe.db.set_value("Fields Layout", "CRM Lead-Quick Entry", "layout", json.dumps(parsed), update_modified=False)
