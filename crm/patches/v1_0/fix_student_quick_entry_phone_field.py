import json

import frappe

QUICK_ENTRY_LAYOUT = '[{"name":"details_section","columns":[{"name":"col_name","fields":["student_name","phone","email"]},{"name":"col_status","fields":["enrollment_status","source","branch"]}]},{"name":"academic_section","columns":[{"name":"col_school","fields":["high_school","major","aspiration"]},{"name":"col_location","fields":["province","ward","admission_year"]}]}]'


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
	for section in parsed:
		for column in section.get("columns", []):
			fields = column.get("fields", [])
			if "mobile_no" in fields:
				column["fields"] = ["phone" if f == "mobile_no" else f for f in fields]
				dirty = True

	if dirty:
		frappe.db.set_value("Fields Layout", "CRM Lead-Quick Entry", "layout", json.dumps(parsed), update_modified=False)
