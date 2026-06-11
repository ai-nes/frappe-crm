"""
Update CRM Contact frontend layouts to reflect restructured DocType:
- Remove stale 'student' field
- Add Parent Information section
- Split Student Profile and Enrollment Information into separate sections
- Add crm_campaign, crm_event, admission_year to correct positions
- Add Notes section to data view
"""

import frappe

QUICK_ENTRY = '[{"name":"details_section","columns":[{"name":"col_name","fields":["full_name","phone","email"]},{"name":"col_stage","fields":["stage","assigned_to","lead_status","admission_year"]}]},{"name":"section_parents","columns":[{"name":"col_parent1","fields":["parent_name"]},{"name":"col_parent2","fields":["parent_phone"]}]},{"name":"admission_section","columns":[{"name":"col_academic","fields":["high_school","province"]},{"name":"col_major","fields":["major","aspiration"]}]},{"name":"section_enrollment","columns":[{"name":"col_enroll1","fields":["source","crm_campaign"]},{"name":"col_enroll2","fields":["branch","crm_event"]}]}]'

SIDE_PANEL = '[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"col_main","fields":["full_name","phone","email","stage","assigned_to","lead_status","admission_year"]}]},{"label":"Parent Information","name":"section_parents","opened":true,"columns":[{"name":"col_parent","fields":["parent_name","parent_phone"]}]},{"label":"Student Profile","name":"section_academic","opened":true,"columns":[{"name":"col_admission","fields":["high_school","province","major","aspiration"]}]},{"label":"Enrollment Information","name":"section_enrollment","opened":true,"columns":[{"name":"col_enroll","fields":["source","branch","crm_campaign","crm_event"]}]}]'

DATA_FIELDS = '[{"name":"first_tab","sections":[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"col_main","fields":["full_name","phone","email"]},{"name":"col_stage","fields":["stage","assigned_to","lead_status","admission_year"]}]},{"label":"Parent Information","name":"section_parents","opened":true,"columns":[{"name":"col_parent1","fields":["parent_name"]},{"name":"col_parent2","fields":["parent_phone"]}]},{"label":"Student Profile","name":"section_academic","opened":true,"columns":[{"name":"col_school","fields":["high_school","province"]},{"name":"col_major","fields":["major","aspiration"]}]},{"label":"Enrollment Information","name":"section_enrollment","opened":true,"columns":[{"name":"col_enroll1","fields":["source","crm_campaign"]},{"name":"col_enroll2","fields":["branch","crm_event"]}]},{"label":"Notes","name":"notes_section","opened":true,"columns":[{"name":"col_notes","fields":["notes"]}]}]}]'


def execute():
    updates = {
        "CRM Contact-Quick Entry": QUICK_ENTRY,
        "CRM Contact-Side Panel": SIDE_PANEL,
        "CRM Contact-Data Fields": DATA_FIELDS,
    }

    for name, layout in updates.items():
        if frappe.db.exists("CRM Fields Layout", name):
            frappe.db.set_value("CRM Fields Layout", name, "layout", layout)

    frappe.clear_cache(doctype="CRM Contact")
