"""
Migrate CRM Contact status fields to unified DocType-based approach:
- Replace old English CRM Enrollment Status records with Vietnamese
- Insert CRM Lead Status records (Vietnamese)
- Migrate existing contact data: map old English values → Vietnamese
- Update CRM Fields Layout records (remove stage, add enrollment_status)
"""

import frappe

# Map old English enrollment status → new Vietnamese
ENROLLMENT_STATUS_MAP = {
	"New": "Mới",
	"Prospect": "Có triển vọng",
	"Confirmed": "Đã xác nhận",
	"Enrolled": "Đã nhập học",
	"Converted": "Đã chuyển đổi",
	"Refused": "Từ chối",
}

# Map old English lead_status (Select values) → new Vietnamese
LEAD_STATUS_MAP = {
	"New": "Mới",
	"No Answer 1": "Không nghe máy lần 1",
	"No Answer 2": "Không nghe máy lần 2",
	"No Answer 3": "Không nghe máy lần 3",
	"Unreachable": "Không liên lạc được",
	"Callback Scheduled": "Hẹn liên hệ sau",
	"Promising": "Có triển vọng",
	"Considering": "Đang suy nghĩ",
	"Not Interested": "Không quan tâm",
	"Not Promising": "Không triển vọng",
	"Wrong Number": "Sai số",
	"Wrong Target": "Sai đối tượng",
	"Financially Unqualified": "Không đủ tài chính",
	"Follow-up Lead": "Lead nhắc lại",
	"Duplicate Lead": "Lead trùng",
	"Converted": "Đã chuyển đổi",
}

LEAD_STATUSES = [
	"Mới",
	"Không nghe máy lần 1",
	"Không nghe máy lần 2",
	"Không nghe máy lần 3",
	"Không liên lạc được",
	"Hẹn liên hệ sau",
	"Có triển vọng",
	"Đang suy nghĩ",
	"Không quan tâm",
	"Không triển vọng",
	"Sai số",
	"Sai đối tượng",
	"Không đủ tài chính",
	"Lead nhắc lại",
	"Lead trùng",
	"Đã chuyển đổi",
]

ENROLLMENT_STATUSES = [
	"Mới",
	"Có triển vọng",
	"Đã xác nhận",
	"Đã nhập học",
	"Đã chuyển đổi",
	"Từ chối",
]

QUICK_ENTRY = '[{"name":"details_section","columns":[{"name":"col_name","fields":["full_name","phone","email"]},{"name":"col_status","fields":["enrollment_status","lead_status","assigned_to","admission_year"]}]},{"name":"section_parents","columns":[{"name":"col_parent1","fields":["parent_name"]},{"name":"col_parent2","fields":["parent_phone"]}]},{"name":"admission_section","columns":[{"name":"col_academic","fields":["high_school","province"]},{"name":"col_major","fields":["major","aspiration"]}]},{"name":"section_enrollment","columns":[{"name":"col_enroll1","fields":["source","crm_campaign"]},{"name":"col_enroll2","fields":["branch","crm_event"]}]}]'

SIDE_PANEL = '[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"col_main","fields":["full_name","phone","email","enrollment_status","lead_status","assigned_to","admission_year"]}]},{"label":"Parent Information","name":"section_parents","opened":true,"columns":[{"name":"col_parent","fields":["parent_name","parent_phone"]}]},{"label":"Student Profile","name":"section_academic","opened":true,"columns":[{"name":"col_admission","fields":["high_school","province","major","aspiration"]}]},{"label":"Enrollment Information","name":"section_enrollment","opened":true,"columns":[{"name":"col_enroll","fields":["source","branch","crm_campaign","crm_event"]}]}]'

DATA_FIELDS = '[{"name":"first_tab","sections":[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"col_main","fields":["full_name","phone","email"]},{"name":"col_status","fields":["enrollment_status","lead_status","assigned_to","admission_year"]}]},{"label":"Parent Information","name":"section_parents","opened":true,"columns":[{"name":"col_parent1","fields":["parent_name"]},{"name":"col_parent2","fields":["parent_phone"]}]},{"label":"Student Profile","name":"section_academic","opened":true,"columns":[{"name":"col_school","fields":["high_school","province"]},{"name":"col_major","fields":["major","aspiration"]}]},{"label":"Enrollment Information","name":"section_enrollment","opened":true,"columns":[{"name":"col_enroll1","fields":["source","crm_campaign"]},{"name":"col_enroll2","fields":["branch","crm_event"]}]},{"label":"Notes","name":"notes_section","opened":true,"columns":[{"name":"col_notes","fields":["notes"]}]}]}]'


def execute():
	if not frappe.db.exists("DocType", "CRM Enrollment Status") or not frappe.db.exists("DocType", "CRM Lead Status"):
		return {"status": "taxonomy_pending"}
	# 1. Seed CRM Lead Status (Vietnamese)
	for status in LEAD_STATUSES:
		if not frappe.db.exists("CRM Lead Status", status):
			doc = frappe.new_doc("CRM Lead Status")
			doc.status_name = status
			doc.insert(ignore_permissions=True)

	# 2. Seed CRM Enrollment Status (Vietnamese), delete old English records
	for eng, vie in ENROLLMENT_STATUS_MAP.items():
		if frappe.db.exists("CRM Enrollment Status", eng):
			frappe.delete_doc("CRM Enrollment Status", eng, ignore_permissions=True, force=True)
	for status in ENROLLMENT_STATUSES:
		if not frappe.db.exists("CRM Enrollment Status", status):
			doc = frappe.new_doc("CRM Enrollment Status")
			doc.status_name = status
			doc.insert(ignore_permissions=True)

	# 3. Migrate existing contact data: English → Vietnamese
	# enrollment_status: map old English DocType values
	for eng, vie in ENROLLMENT_STATUS_MAP.items():
		frappe.db.sql(
			"UPDATE `tabCRM Contact` SET enrollment_status = %s WHERE enrollment_status = %s",
			(vie, eng),
		)
	# enrollment_status: set default for blank contacts
	frappe.db.sql(
		"UPDATE `tabCRM Contact` SET enrollment_status = 'Mới' WHERE (enrollment_status IS NULL OR enrollment_status = '')"
	)
	# lead_status: map old English Select values → Vietnamese Link values
	for eng, vie in LEAD_STATUS_MAP.items():
		frappe.db.sql(
			"UPDATE `tabCRM Contact` SET lead_status = %s WHERE lead_status = %s",
			(vie, eng),
		)

	# 4. Update CRM Fields Layout
	layouts = {
		"CRM Contact-Quick Entry": QUICK_ENTRY,
		"CRM Contact-Side Panel": SIDE_PANEL,
		"CRM Contact-Data Fields": DATA_FIELDS,
	}
	for name, layout in layouts.items():
		if frappe.db.exists("Fields Layout", name):
			frappe.db.set_value("Fields Layout", name, "layout", layout)

	frappe.clear_cache(doctype="CRM Contact")
