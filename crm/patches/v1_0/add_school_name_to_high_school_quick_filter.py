import json

import frappe


def execute():
	"""Add the missing school_name quick filter so users can search High Schools by name."""
	global_settings = frappe.db.exists("Global Settings", {"dt": "CRM High School", "type": "Quick Filters"})
	if not global_settings:
		return

	quick_filters = json.loads(frappe.db.get_value("Global Settings", global_settings, "json") or "[]")
	if "school_name" in quick_filters:
		return

	quick_filters.insert(0, "school_name")
	frappe.db.set_value("Global Settings", global_settings, "json", json.dumps(quick_filters))
