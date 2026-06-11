"""
Migrate CRM Contact status fields to unified DocType-based approach:
- Insert CRM Lead Status records from old hardcoded Select options
- Insert CRM Enrollment Status records (if not already seeded)
- Migrate existing lead_status string values to Link values
- Update CRM Fields Layout records (remove stage, add enrollment_status)
"""

import frappe

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

DATA_FIELDS = '[{"name":"first_tab","sections":[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"col_main","fields":["full_name","phone","email"]},{"name":"col_status","fields":["enrollment_status","lead_status","assigned_to","admission_year"]}]},{"label":"Parent Information","name":"section_parents","opened":true,"columns":[{"name":"col_parent1","fields":["parent_name"]},{"name":"col_parent2","fields":["parent_phone"]}]},{"label":"Student Profile","name":"section_academic","opened":true,"columns":[{"name":"col_school","fields":["high_school","province"]},{"name":"col_major","fields":["major","aspiration"]}]},{"label":"Enrollment Information","name":"section_enrollment","opened":true,"columns":[{"name":"col_enroll1","fields":["source","crm_campaign"]},{"name":"col_enroll2","fields":["branch","crm_event"]}]},{"label":"Academic & Scores","name":"section_academic_history","opened":false,"columns":[{"name":"col_scores1","fields":["cohort_start_year","education_program","graduation_score","transcript_score"]},{"name":"col_scores2","fields":["cohort_end_year","admission_method","english_converted_score","total_score"]}]},{"label":"Results","name":"section_academic_tables","opened":false,"columns":[{"name":"col_tables","fields":["academic_results","language_certificates"]}]},{"label":"Notes","name":"notes_section","opened":true,"columns":[{"name":"col_notes","fields":["notes"]}]}]}]'


def execute():
	# 1. Seed CRM Lead Status records
	for status in LEAD_STATUSES:
		if not frappe.db.exists("CRM Lead Status", status):
			doc = frappe.new_doc("CRM Lead Status")
			doc.status_name = status
			doc.insert(ignore_permissions=True)

	# 2. Seed CRM Enrollment Status records
	for status in ENROLLMENT_STATUSES:
		if not frappe.db.exists("CRM Enrollment Status", status):
			doc = frappe.new_doc("CRM Enrollment Status")
			doc.status_name = status
			doc.insert(ignore_permissions=True)

	# 3. Migrate existing lead_status values (already valid Link keys — same strings)
	# The old Select values match the new DocType names, so no data transform needed.
	# Set enrollment_status = "New" for contacts that have none.
	frappe.db.sql(
		"""UPDATE `tabCRM Contact`
		   SET enrollment_status = 'Mới'
		   WHERE (enrollment_status IS NULL OR enrollment_status = '')"""
	)

	# 4. Update CRM Fields Layout
	layouts = {
		"CRM Contact-Quick Entry": QUICK_ENTRY,
		"CRM Contact-Side Panel": SIDE_PANEL,
		"CRM Contact-Data Fields": DATA_FIELDS,
	}
	for name, layout in layouts.items():
		if frappe.db.exists("CRM Fields Layout", name):
			frappe.db.set_value("CRM Fields Layout", name, "layout", layout)

	frappe.clear_cache(doctype="CRM Contact")
