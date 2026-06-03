# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt
import json

import click
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from crm.fcrm.doctype.crm_dashboard.crm_dashboard import create_default_manager_dashboard


def before_install():
	pass


def after_install(force=False):
	add_default_fields_layout(force)
	add_property_setter()
	add_email_template_custom_fields()
	add_email_account_custom_field()
	add_default_lead_sources()
	add_default_lost_reasons()
	add_default_quick_filters()
	add_standard_dropdown_items()
	create_default_manager_dashboard(force)
	create_assignment_rule_custom_fields()
	add_assignment_rule_property_setters()
	sync_frappe_crm_workspace()
	frappe.db.commit()


def sync_frappe_crm_workspace():
	"""Import the Frappe CRM Desk workspace from crm/fcrm/workspace/frappe_crm/frappe_crm.json."""
	frappe.reload_doc("fcrm", "Workspace", "Frappe CRM", force=True)


def add_default_fields_layout(force=False):
	quick_entry_layouts = {
		"CRM Contact-Quick Entry": {
			"doctype": "CRM Contact",
			"layout": '[{"name":"details_section","columns":[{"name":"column_name","fields":["full_name","phone","email"]},{"name":"column_stage","fields":["stage","assigned_to"]}]},{"name":"admission_section","columns":[{"name":"column_academic","fields":["student","high_school","major"]},{"name":"column_source","fields":["source","campaign","crm_event"]}]}]',
		},
		"Enrollment Student-Quick Entry": {
			"doctype": "Enrollment Student",
			"layout": '[{"name":"details_section","columns":[{"name":"column_name","fields":["student_name","mobile_no","email"]},{"name":"column_status","fields":["enrollment_status","source"]}]},{"name":"academic_section","columns":[{"name":"column_school","fields":["high_school","major"]},{"name":"column_location","fields":["branch","province","ward"]}]}]',
		},
		"Contact-Quick Entry": {
			"doctype": "Contact",
			"layout": '[{"name": "salutation_section", "columns": [{"name": "column_eXks", "fields": ["salutation"]}]}, {"name": "full_name_section", "hideBorder": true, "columns": [{"name": "column_cSxf", "fields": ["first_name"]}, {"name": "column_yBc7", "fields": ["last_name"]}]}, {"name": "email_section", "hideBorder": true, "columns": [{"name": "column_tH3L", "fields": ["email_id"]}]}, {"name": "mobile_gender_section", "hideBorder": true, "columns": [{"name": "column_lrfI", "fields": ["mobile_no"]}, {"name": "column_Tx3n", "fields": ["gender"]}]}, {"name": "company_section", "hideBorder": true, "columns": [{"name": "column_S0J8", "fields": ["company_name"]}]}, {"name": "designation_section", "hideBorder": true, "columns": [{"name": "column_bsO8", "fields": ["designation"]}]}, {"name": "address_section", "hideBorder": true, "columns": [{"name": "column_W3VY", "fields": ["address"]}]}]',
		},
		"Address-Quick Entry": {
			"doctype": "Address",
			"layout": '[{"name": "details_section", "columns": [{"name": "column_uSSG", "fields": ["address_title", "address_type", "address_line1", "address_line2", "city", "state", "country", "pincode"]}]}]',
		},
		"CRM Call Log-Quick Entry": {
			"doctype": "CRM Call Log",
			"layout": '[{"name":"details_section","columns":[{"name":"column_uMSG","fields":["type","from","duration"]},{"name":"column_wiZT","fields":["to","status","caller","receiver"]}]}]',
		},
		"FCRM Note-Quick Entry": {
			"doctype": "FCRM Note",
			"layout": '[{"name":"details_section","columns":[{"name":"column_o2s9","fields":["title", "content"]}]}]',
		},
		"CRM Task-Quick Entry": {
			"doctype": "CRM Task",
			"layout": '[{"name":"first_tab","sections":[{"name":"details_section","columns":[{"name":"column_X9sG","fields":["title","description"]}]},{"name":"assignment_section","columns":[{"name":"column_9XjK","fields":["priority","due_date"]},{"name":"column_7s8n","fields":["assigned_to","status"]}],"hideBorder":true}]}]',
		},
	}

	sidebar_fields_layouts = {
		"CRM Contact-Side Panel": {
			"doctype": "CRM Contact",
			"layout": '[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"column_main","fields":["full_name","phone","email","stage","assigned_to"]}]},{"label":"Admission","name":"admission_section","opened":true,"columns":[{"name":"column_admission","fields":["student","high_school","major","source","campaign","crm_event"]}]}]',
		},
		"Enrollment Student-Side Panel": {
			"doctype": "Enrollment Student",
			"layout": '[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"column_main","fields":["student_name","mobile_no","email","enrollment_status","converted"]}]},{"label":"Admission","name":"admission_section","opened":true,"columns":[{"name":"column_admission","fields":["high_school","major","source","branch","province","ward","admission_year"]}]}]',
		},
		"Contact-Side Panel": {
			"doctype": "Contact",
			"layout": '[{"label": "Details", "name": "details_section", "opened": true, "columns": [{"name": "column_eIWl", "fields": ["salutation", "first_name", "last_name", "email_id", "mobile_no", "gender", "company_name", "designation", "address"]}]}]',
		},
	}

	data_fields_layouts = {
		"CRM Contact-Data Fields": {
			"doctype": "CRM Contact",
			"layout": '[{"name":"first_tab","sections":[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"column_main","fields":["full_name","phone","email"]},{"name":"column_stage","fields":["stage","assigned_to"]}]},{"label":"Admission","name":"admission_section","opened":true,"columns":[{"name":"column_academic","fields":["student","high_school","major"]},{"name":"column_source","fields":["source","campaign","crm_event"]}]}]}]',
		},
		"Enrollment Student-Data Fields": {
			"doctype": "Enrollment Student",
			"layout": '[{"name":"first_tab","sections":[{"label":"Details","name":"details_section","opened":true,"columns":[{"name":"column_main","fields":["student_name","mobile_no","email"]},{"name":"column_status","fields":["enrollment_status","converted"]}]},{"label":"Admission","name":"admission_section","opened":true,"columns":[{"name":"column_academic","fields":["high_school","major","source"]},{"name":"column_location","fields":["branch","province","ward","admission_year"]}]}]}]',
		},
	}

	for layout in quick_entry_layouts:
		if frappe.db.exists("CRM Fields Layout", layout):
			if force:
				frappe.delete_doc("CRM Fields Layout", layout)
			else:
				continue

		doc = frappe.new_doc("CRM Fields Layout")
		doc.type = "Quick Entry"
		doc.dt = quick_entry_layouts[layout]["doctype"]
		doc.layout = quick_entry_layouts[layout]["layout"]
		doc.insert()

	for layout in sidebar_fields_layouts:
		if frappe.db.exists("CRM Fields Layout", layout):
			if force:
				frappe.delete_doc("CRM Fields Layout", layout)
			else:
				continue

		doc = frappe.new_doc("CRM Fields Layout")
		doc.type = "Side Panel"
		doc.dt = sidebar_fields_layouts[layout]["doctype"]
		doc.layout = sidebar_fields_layouts[layout]["layout"]
		doc.insert()

	for layout in data_fields_layouts:
		if frappe.db.exists("CRM Fields Layout", layout):
			if force:
				frappe.delete_doc("CRM Fields Layout", layout)
			else:
				continue

		doc = frappe.new_doc("CRM Fields Layout")
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
		"Campaign",
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


def add_default_quick_filters():
	quick_filters = {
		"Enrollment Student": ["student_name", "mobile_no", "email", "enrollment_status", "source"],
		"CRM Contact": ["full_name", "phone", "email", "stage", "assigned_to", "source"],
		"CRM High School": ["school_code", "school_type", "ward", "province"],
		"Contact": ["status", "email_id", "phone"],
		"CRM Task": ["title", "priority", "assigned_to", "status", "due_date"],
		"CRM Call Log": ["telephony_medium", "type", "status", "from", "to"],
	}

	for quick_filter in quick_filters:
		if frappe.db.exists("CRM Global Settings", {"dt": quick_filter}):
			continue

		doc = frappe.new_doc("CRM Global Settings")
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
