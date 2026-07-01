# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt
import json

import click
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from crm.fcrm.doctype.dashboard.dashboard import create_default_manager_dashboard


CHATWOOT_CORS_ORIGIN = "https://app.chatwoot.com"


def before_install():
	pass


def after_install(force=False):
	add_chatwoot_cors_origin()
	add_default_fields_layout(force)
	add_property_setter()
	add_email_template_custom_fields()
	add_email_account_custom_field()
	add_default_lead_sources()
	add_default_lost_reasons()
	add_default_lead_statuses()
	add_default_enrollment_statuses()
	add_default_quick_filters()
	add_standard_dropdown_items()
	create_default_manager_dashboard(force)
	create_assignment_rule_custom_fields()
	add_assignment_rule_property_setters()
	sync_frappe_crm_workspace()
	frappe.db.commit()


def add_chatwoot_cors_origin():
	"""Allow Chatwoot dashboard requests to reach this site."""

	current_allow_cors = frappe.conf.get("allow_cors")

	if current_allow_cors == "*":
		return

	if not current_allow_cors:
		allow_cors = CHATWOOT_CORS_ORIGIN
	elif isinstance(current_allow_cors, list):
		if CHATWOOT_CORS_ORIGIN in current_allow_cors:
			return
		allow_cors = [*current_allow_cors, CHATWOOT_CORS_ORIGIN]
	elif isinstance(current_allow_cors, str):
		origins = [origin.strip() for origin in current_allow_cors.split(",") if origin.strip()]
		if CHATWOOT_CORS_ORIGIN in origins:
			return
		allow_cors = ",".join([*origins, CHATWOOT_CORS_ORIGIN])
	else:
		allow_cors = CHATWOOT_CORS_ORIGIN

	site_config_path = frappe.get_site_path("site_config.json")
	with open(site_config_path) as site_config_file:
		site_config = json.load(site_config_file)

	site_config["allow_cors"] = allow_cors

	with open(site_config_path, "w") as site_config_file:
		json.dump(site_config, site_config_file, indent=1)
		site_config_file.write("\n")

	frappe.conf.allow_cors = allow_cors
	click.secho(f"* Allowing CORS for {CHATWOOT_CORS_ORIGIN}")


def sync_frappe_crm_workspace():
	"""Import the Frappe CRM Desk workspace from crm/fcrm/workspace/frappe_crm/frappe_crm.json."""
	frappe.reload_doc("fcrm", "Workspace", "Frappe CRM", force=True)


def add_default_fields_layout(force=False):
	quick_entry_layouts = {
		"CRM Contact-Quick Entry": {
			"doctype": "CRM Contact",
			"layout": '[{"name":"details_section","columns":[{"name":"col_name","fields":["full_name","phone","email"]},{"name":"col_status","fields":["enrollment_status","lead_status","assigned_to","admission_year"]}]},{"name":"section_parents","columns":[{"name":"col_parent1","fields":["parent_name"]},{"name":"col_parent2","fields":["parent_phone"]}]},{"name":"admission_section","columns":[{"name":"col_academic","fields":["province","high_school"]},{"name":"col_major","fields":["major","aspiration"]}]},{"name":"section_enrollment","columns":[{"name":"col_enroll1","fields":["source","crm_campaign"]},{"name":"col_enroll2","fields":["branch","crm_event"]}]}]',
		},
		"CRM Student-Quick Entry": {
			"doctype": "CRM Student",
			"layout": '[{"name":"details_section","columns":[{"name":"col_name","fields":["student_name","phone","email"]},{"name":"col_status","fields":["enrollment_status","source","branch"]}]},{"name":"academic_section","columns":[{"name":"col_location","fields":["province","high_school","major"]},{"name":"col_admission","fields":["ward","admission_year","aspiration"]}]}]',
		},
		"Contact-Quick Entry": {
			"doctype": "Contact",
			"layout": '[{"name": "salutation_section", "columns": [{"name": "column_eXks", "fields": ["salutation"]}]}, {"name": "full_name_section", "hideBorder": true, "columns": [{"name": "column_cSxf", "fields": ["first_name"]}, {"name": "column_yBc7", "fields": ["last_name"]}]}, {"name": "email_section", "hideBorder": true, "columns": [{"name": "column_tH3L", "fields": ["email_id"]}]}, {"name": "mobile_gender_section", "hideBorder": true, "columns": [{"name": "column_lrfI", "fields": ["mobile_no"]}, {"name": "column_Tx3n", "fields": ["gender"]}]}, {"name": "company_section", "hideBorder": true, "columns": [{"name": "column_S0J8", "fields": ["company_name"]}]}, {"name": "designation_section", "hideBorder": true, "columns": [{"name": "column_bsO8", "fields": ["designation"]}]}, {"name": "address_section", "hideBorder": true, "columns": [{"name": "column_W3VY", "fields": ["address"]}]}]',
		},
		"Address-Quick Entry": {
			"doctype": "Address",
			"layout": '[{"name": "details_section", "columns": [{"name": "column_uSSG", "fields": ["address_title", "address_type", "address_line1", "address_line2", "city", "state", "country", "pincode"]}]}]',
		},
		"Call Log-Quick Entry": {
			"doctype": "Call Log",
			"layout": '[{"name":"details_section","columns":[{"name":"column_uMSG","fields":["type","from","duration"]},{"name":"column_wiZT","fields":["to","status","caller","receiver"]}]}]',
		},
		"CRM Person-Quick Entry": {
			"doctype": "CRM Person",
			"layout": '[{"name":"details_section","columns":[{"name":"col_name","fields":["full_name","role","phone","email"]},{"name":"col_school","fields":["province","high_school"]}]}]',
		},
		"FCRM Note-Quick Entry": {
			"doctype": "FCRM Note",
			"layout": '[{"name":"details_section","columns":[{"name":"column_o2s9","fields":["title", "content"]}]}]',
		},
		"Task-Quick Entry": {
			"doctype": "Task",
			"layout": '[{"name":"first_tab","sections":[{"name":"details_section","columns":[{"name":"column_X9sG","fields":["title","description"]}]},{"name":"assignment_section","columns":[{"name":"column_9XjK","fields":["priority","due_date"]},{"name":"column_7s8n","fields":["assigned_to","status"]}],"hideBorder":true}]}]',
		},
	}

	sidebar_fields_layouts = {
		"CRM Contact-Side Panel": {
			"doctype": "CRM Contact",
			"layout": '[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"col_main","fields":["full_name","phone","email","enrollment_status","lead_status","assigned_to","admission_year"]}]},{"label":"Parent Information","name":"section_parents","opened":true,"columns":[{"name":"col_parent","fields":["parent_name","parent_phone"]}]},{"label":"Student Profile","name":"section_academic","opened":true,"columns":[{"name":"col_admission","fields":["province","high_school","major","aspiration"]}]},{"label":"Enrollment Information","name":"section_enrollment","opened":true,"columns":[{"name":"col_enroll","fields":["source","branch","crm_campaign","crm_event"]}]}]',
		},
		"CRM Student-Side Panel": {
			"doctype": "CRM Student",
			"layout": '[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"col_main","fields":["student_name","phone","email","enrollment_status","branch"]}]},{"label":"Admission","name":"admission_section","opened":true,"columns":[{"name":"col_admission","fields":["source","province","ward","high_school","major","aspiration","admission_year"]}]},{"label":"Academic & Scores","name":"section_academic_history","opened":true,"columns":[{"name":"col_scores","fields":["cohort_start_year","cohort_end_year","education_program","admission_method","graduation_score","transcript_score","english_converted_score","total_score"]}]}]',
		},
		"CRM High School-Side Panel": {
			"doctype": "CRM High School",
			"layout": '[{"label":"School Info","name":"school_section","opened":true,"columns":[{"name":"col_main","fields":["school_name","school_code","school_type"]}]},{"label":"Location","name":"location_section","opened":true,"columns":[{"name":"col_loc","fields":["ward","province_name","region"]}]},{"label":"Contact","name":"contact_section","opened":true,"columns":[{"name":"col_contact","fields":["address","phone","email"]}]}]',
		},
		"CRM Person-Side Panel": {
			"doctype": "CRM Person",
			"layout": '[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"col_main","fields":["full_name","role","phone","email"]}]},{"label":"School","name":"school_section","opened":true,"columns":[{"name":"col_school","fields":["province","high_school","notes"]}]}]',
		},
		"CRM Campaign-Side Panel": {
			"doctype": "CRM Campaign",
			"layout": '[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"col_main","fields":["title","campus","campaign_type","start_date","end_date","budget","notes"]}]}]',
		},
		"CRM Event-Side Panel": {
			"doctype": "CRM Event",
			"layout": '[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"col_main","fields":["title","crm_campaign","province","event_date","location","notes"]}]}]',
		},
		"Contact-Side Panel": {
			"doctype": "Contact",
			"layout": '[{"label": "Details", "name": "details_section", "opened": true, "columns": [{"name": "column_eIWl", "fields": ["salutation", "first_name", "last_name", "email_id", "mobile_no", "gender", "company_name", "designation", "address"]}]}]',
		},
	}

	data_fields_layouts = {
		"CRM Contact-Data Fields": {
			"doctype": "CRM Contact",
			"layout": '[{"name":"first_tab","sections":[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"col_main","fields":["full_name","phone","email"]},{"name":"col_status","fields":["enrollment_status","lead_status","assigned_to","admission_year"]}]},{"label":"Parent Information","name":"section_parents","opened":true,"columns":[{"name":"col_parent1","fields":["parent_name"]},{"name":"col_parent2","fields":["parent_phone"]}]},{"label":"Student Profile","name":"section_academic","opened":true,"columns":[{"name":"col_school","fields":["province","high_school"]},{"name":"col_major","fields":["major","aspiration"]}]},{"label":"Enrollment Information","name":"section_enrollment","opened":true,"columns":[{"name":"col_enroll1","fields":["source","crm_campaign"]},{"name":"col_enroll2","fields":["branch","crm_event"]}]},{"label":"Academic & Scores","name":"section_academic_history","opened":false,"columns":[{"name":"col_scores1","fields":["cohort_start_year","education_program","graduation_score","transcript_score"]},{"name":"col_scores2","fields":["cohort_end_year","admission_method","english_converted_score","total_score"]}]},{"label":"Results","name":"section_academic_tables","opened":false,"columns":[{"name":"col_tables","fields":["academic_results","language_certificates"]}]},{"label":"Notes","name":"notes_section","opened":true,"columns":[{"name":"col_notes","fields":["notes"]}]}]}]',
		},
		"CRM Student-Data Fields": {
			"doctype": "CRM Student",
			"layout": '[{"name":"first_tab","sections":[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"col_main","fields":["student_name","phone","email"]},{"name":"col_status","fields":["enrollment_status","branch"]}]},{"label":"Admission","name":"admission_section","opened":true,"columns":[{"name":"col_location","fields":["source","province","high_school","major"]},{"name":"col_academic","fields":["ward","admission_year","aspiration"]}]},{"label":"Academic & Scores","name":"section_academic_history","opened":true,"columns":[{"name":"col_scores1","fields":["cohort_start_year","education_program","graduation_score","transcript_score"]},{"name":"col_scores2","fields":["cohort_end_year","admission_method","english_converted_score","total_score"]}]},{"label":"Results","name":"section_academic_tables","opened":true,"columns":[{"name":"col_tables","fields":["academic_results","language_certificates"]}]},{"label":"Notes","name":"notes_section","opened":true,"columns":[{"name":"col_notes","fields":["notes"]}]}]}]',
		},
		"CRM High School-Data Fields": {
			"doctype": "CRM High School",
			"layout": '[{"name":"first_tab","sections":[{"label":"School Info","name":"school_section","opened":true,"columns":[{"name":"col_basic","fields":["school_name","school_code","school_type"]},{"name":"col_contact","fields":["address","phone","email"]}]},{"label":"Location","name":"location_section","opened":true,"columns":[{"name":"col_location","fields":["ward","province_name","region"]}]}]}]',
		},
	}

	for layout in quick_entry_layouts:
		if frappe.db.exists("Fields Layout", layout):
			if force:
				frappe.delete_doc("Fields Layout", layout)
			else:
				continue

		doc = frappe.new_doc("Fields Layout")
		doc.type = "Quick Entry"
		doc.dt = quick_entry_layouts[layout]["doctype"]
		doc.layout = quick_entry_layouts[layout]["layout"]
		doc.insert()

	for layout in sidebar_fields_layouts:
		if frappe.db.exists("Fields Layout", layout):
			if force:
				frappe.delete_doc("Fields Layout", layout)
			else:
				continue

		doc = frappe.new_doc("Fields Layout")
		doc.type = "Side Panel"
		doc.dt = sidebar_fields_layouts[layout]["doctype"]
		doc.layout = sidebar_fields_layouts[layout]["layout"]
		doc.insert()

	for layout in data_fields_layouts:
		if frappe.db.exists("Fields Layout", layout):
			if force:
				frappe.delete_doc("Fields Layout", layout)
			else:
				continue

		doc = frappe.new_doc("Fields Layout")
		doc.type = "Data Fields"
		doc.dt = data_fields_layouts[layout]["doctype"]
		doc.layout = data_fields_layouts[layout]["layout"]
		doc.insert()


def add_property_setter():
	if not frappe.db.exists("Property Setter", {"name": "Contact-main-search_fields"}):
		doc = frappe.new_doc("Property Setter")
		doc.doctype_or_field = "DocType"
		doc.doc_type = "Contact"
		doc.property = "search_fields"
		doc.property_type = "Data"
		doc.value = "email_id"
		doc.insert()


def add_email_template_custom_fields():
	if not frappe.get_meta("Email Template").has_field("enabled"):
		click.secho("* Installing Custom Fields in Email Template")

		create_custom_fields(
			{
				"Email Template": [
					{
						"default": "0",
						"fieldname": "enabled",
						"fieldtype": "Check",
						"label": "Enabled",
						"insert_after": "",
					},
					{
						"fieldname": "reference_doctype",
						"fieldtype": "Link",
						"label": "Doctype",
						"options": "DocType",
						"insert_after": "enabled",
					},
				]
			}
		)

		frappe.clear_cache(doctype="Email Template")


def add_email_account_custom_field():
	if not frappe.get_meta("Email Account").has_field("create_crm_contact_from_incoming_email"):
		click.secho("* Installing Custom Fields in Email Account")

		create_custom_fields(
			{
				"Email Account": [
					{
						"default": "0",
						"fieldname": "create_crm_contact_from_incoming_email",
						"fieldtype": "Check",
						"label": "Create CRM Contact from Incoming Emails",
						"description": "Automatically create a CRM contact when an incoming email is received from an unknown contact",
						"insert_after": "create_contact",
					}
				]
			}
		)

		frappe.clear_cache(doctype="Email Account")


def add_default_lead_sources():
	lead_sources = [
		"Email",
		"Existing Customer",
		"Reference",
		"Advertisement",
		"Cold Calling",
		"Exhibition",
		"Supplier Reference",
		"Mass Mailing",
		"Customer's Vendor",
		"CRM Campaign",
		"Walk In",
		"Facebook",
		"Website",
	]

	for source in lead_sources:
		if frappe.db.exists("CRM Lead Source", source):
			continue

		doc = frappe.new_doc("CRM Lead Source")
		doc.source_name = source
		doc.insert()


def add_default_lost_reasons():
	lost_reasons = [
		{
			"reason": "Pricing",
			"description": "The prospect found the pricing to be too high or not competitive.",
		},
		{"reason": "Competition", "description": "The prospect chose a competitor's product or service."},
		{
			"reason": "Budget Constraints",
			"description": "The prospect did not have the budget to proceed with the purchase.",
		},
		{
			"reason": "Missing Features",
			"description": "The prospect felt that the product or service was missing key features they needed.",
		},
		{
			"reason": "Long Sales Cycle",
			"description": "The sales process took too long, leading to loss of interest.",
		},
		{
			"reason": "No Decision-Maker",
			"description": "The prospect was not the decision-maker and could not proceed.",
		},
		{"reason": "Unresponsive Prospect", "description": "The prospect did not respond to follow-ups."},
		{"reason": "Poor Fit", "description": "The prospect was not a good fit for the product or service."},
		{"reason": "Other", "description": ""},
	]

	for reason in lost_reasons:
		if frappe.db.exists("CRM Lost Reason", reason["reason"]):
			continue

		doc = frappe.new_doc("CRM Lost Reason")
		doc.lost_reason = reason["reason"]
		doc.description = reason["description"]
		doc.insert()


def add_default_lead_statuses():
	lead_statuses = [
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

	for status in lead_statuses:
		if frappe.db.exists("CRM Lead Status", status):
			continue

		doc = frappe.new_doc("CRM Lead Status")
		doc.status_name = status
		doc.insert()


def add_default_enrollment_statuses():
	enrollment_statuses = [
		"Mới",
		"Có triển vọng",
		"Đã xác nhận",
		"Đã nhập học",
		"Đã chuyển đổi",
		"Từ chối",
	]

	for status in enrollment_statuses:
		if frappe.db.exists("CRM Enrollment Status", status):
			continue

		doc = frappe.new_doc("CRM Enrollment Status")
		doc.status_name = status
		doc.insert()


def add_default_quick_filters():
	quick_filters = {
		"CRM Student": ["student_name", "phone", "email", "enrollment_status", "assigned_to", "source"],
		"CRM Contact": ["full_name", "phone", "email", "enrollment_status", "assigned_to", "source"],
		"CRM High School": ["province_name", "ward_name", "school_name"],
		"Contact": ["status", "email_id", "phone"],
		"Task": ["title", "priority", "assigned_to", "status", "due_date"],
		"Call Log": ["telephony_medium", "type", "status", "from", "to"],
	}

	for quick_filter in quick_filters:
		if frappe.db.exists("Global Settings", {"dt": quick_filter}):
			continue

		doc = frappe.new_doc("Global Settings")
		doc.dt = quick_filter
		doc.json = json.dumps(quick_filters[quick_filter])
		doc.insert()


def add_standard_dropdown_items():
	crm_settings = frappe.get_single("FCRM Settings")

	# don't add dropdown items if they're already present
	if crm_settings.dropdown_items:
		return

	crm_settings.dropdown_items = []

	for item in frappe.get_hooks("standard_dropdown_items"):
		crm_settings.append("dropdown_items", item)

	crm_settings.save()


def add_assignment_rule_property_setters():
	"""Add a property setter to the Assignment Rule DocType for assign_condition and unassign_condition."""

	default_fields = {
		"doctype": "Property Setter",
		"doctype_or_field": "DocField",
		"doc_type": "Assignment Rule",
		"property_type": "Data",
		"is_system_generated": 1,
	}

	if not frappe.db.exists("Property Setter", {"name": "Assignment Rule-assign_condition-depends_on"}):
		frappe.get_doc(
			{
				**default_fields,
				"name": "Assignment Rule-assign_condition-depends_on",
				"field_name": "assign_condition",
				"property": "depends_on",
				"value": "eval: !doc.assign_condition_json",
			}
		).insert()
	else:
		frappe.db.set_value(
			"Property Setter",
			{"name": "Assignment Rule-assign_condition-depends_on"},
			"value",
			"eval: !doc.assign_condition_json",
		)
	if not frappe.db.exists("Property Setter", {"name": "Assignment Rule-unassign_condition-depends_on"}):
		frappe.get_doc(
			{
				**default_fields,
				"name": "Assignment Rule-unassign_condition-depends_on",
				"field_name": "unassign_condition",
				"property": "depends_on",
				"value": "eval: !doc.unassign_condition_json",
			}
		).insert()
	else:
		frappe.db.set_value(
			"Property Setter",
			{"name": "Assignment Rule-unassign_condition-depends_on"},
			"value",
			"eval: !doc.unassign_condition_json",
		)


def create_assignment_rule_custom_fields():
	if not frappe.get_meta("Assignment Rule").has_field("assign_condition_json"):
		click.secho("* Installing Custom Fields in Assignment Rule")

		create_custom_fields(
			{
				"Assignment Rule": [
					{
						"description": "Autogenerated field by CRM App",
						"fieldname": "assign_condition_json",
						"fieldtype": "Code",
						"label": "Assign Condition JSON",
						"insert_after": "assign_condition",
						"depends_on": "eval: doc.assign_condition_json",
					},
					{
						"description": "Autogenerated field by CRM App",
						"fieldname": "unassign_condition_json",
						"fieldtype": "Code",
						"label": "Unassign Condition JSON",
						"insert_after": "unassign_condition",
						"depends_on": "eval: doc.unassign_condition_json",
					},
				],
			}
		)

		frappe.clear_cache(doctype="Assignment Rule")
