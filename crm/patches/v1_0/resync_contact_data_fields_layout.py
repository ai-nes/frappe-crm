"""Re-apply the CRM Contact Data Fields layout without retired fields."""

import frappe


DATA_FIELDS = '[{"name":"first_tab","sections":[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"col_main","fields":["full_name","phone","email"]},{"name":"col_status","fields":["enrollment_status","assigned_to","admission_year"]}]},{"label":"Parent Information","name":"section_parents","opened":true,"columns":[{"name":"col_parent1","fields":["parent_name"]},{"name":"col_parent2","fields":["parent_phone"]}]},{"label":"Student Profile","name":"section_academic","opened":true,"columns":[{"name":"col_school","fields":["high_school","province"]},{"name":"col_major","fields":["major","aspiration"]}]},{"label":"Enrollment Information","name":"section_enrollment","opened":true,"columns":[{"name":"col_enroll1","fields":["source","crm_campaign"]},{"name":"col_enroll2","fields":["branch","crm_event"]}]},{"label":"Notes","name":"notes_section","opened":true,"columns":[{"name":"col_notes","fields":["notes"]}]}]}]'


def execute():
	if frappe.db.exists("Fields Layout", "CRM Student-Data Fields"):
		frappe.db.set_value("Fields Layout", "CRM Student-Data Fields", "layout", DATA_FIELDS)
		frappe.clear_cache(doctype="CRM Student")
