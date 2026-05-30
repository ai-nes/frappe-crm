# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json
import os

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	picklists = _load_picklists()

	_add_crm_lead_fields(picklists)
	_add_crm_organization_fields()
	_add_contact_fields()
	_update_lead_side_panel()

	frappe.db.commit()


def _load_picklists():
	path = os.path.join(frappe.get_app_path("crm"), "migration", "fixtures", "picklists.json")
	if os.path.exists(path):
		with open(path, encoding="utf-8") as f:
			return json.load(f)
	return {}


def _options(picklists, key, fallback=""):
	values = picklists.get(key, [])
	return "\n".join(v for v in values if not v.startswith("_")) if values else fallback


def _add_crm_lead_fields(picklists):
	ad_channel_opts = _options(picklists, "ad_channel", "Facebook\nWebsite\nZalo\nGoogle\nKhác")
	aspiration_opts = _options(picklists, "fpt_aspiration", "Nguyện vọng 1\nNguyện vọng 2\nNguyện vọng 3")
	potential_opts = _options(picklists, "conversion_potential", "Nóng\nẤm\nLạnh")

	custom_fields = {
		"CRM Lead": [
			{
				"fieldname": "province",
				"fieldtype": "Link",
				"label": "Tỉnh/Thành phố",
				"options": "CRM Province",
				"insert_after": "organization",
			},
			{
				"fieldname": "high_school",
				"fieldtype": "Link",
				"label": "Trường THPT",
				"options": "CRM Organization",
				"insert_after": "province",
			},
			{
				"fieldname": "major",
				"fieldtype": "Link",
				"label": "Ngành quan tâm",
				"options": "CRM Major",
				"insert_after": "high_school",
			},
			{
				"fieldname": "branch",
				"fieldtype": "Link",
				"label": "Chi nhánh",
				"options": "CRM Branch",
				"insert_after": "major",
			},
			{
				"fieldname": "ad_channel",
				"fieldtype": "Select",
				"label": "Kênh quảng cáo",
				"options": ad_channel_opts,
				"insert_after": "source",
			},
			{
				"fieldname": "segments",
				"fieldtype": "Small Text",
				"label": "Segments",
				"insert_after": "ad_channel",
			},
			{
				"fieldname": "fpt_aspiration",
				"fieldtype": "Select",
				"label": "Nguyện vọng FPT",
				"options": aspiration_opts,
				"insert_after": "segments",
			},
			{
				"fieldname": "conversion_potential",
				"fieldtype": "Select",
				"label": "Khả năng chuyển đổi",
				"options": potential_opts,
				"insert_after": "fpt_aspiration",
			},
			{
				"fieldname": "other_email",
				"fieldtype": "Data",
				"label": "Email khác",
				"options": "Email",
				"insert_after": "email",
			},
			{
				"fieldname": "linked_contact",
				"fieldtype": "Link",
				"label": "Học viên liên kết",
				"options": "Contact",
				"insert_after": "branch",
			},
			{
				"fieldname": "nvfpt",
				"fieldtype": "Small Text",
				"label": "Nhân viên FPT",
				"insert_after": "linked_contact",
			},
			{
				"fieldname": "tags",
				"fieldtype": "Small Text",
				"label": "Tags",
				"insert_after": "nvfpt",
			},
			{
				"fieldname": "import_source_id",
				"fieldtype": "Int",
				"label": "Import Source ID",
				"hidden": 1,
				"insert_after": "linked_contact",
			},
		]
	}
	create_custom_fields(custom_fields, ignore_validate=True)


def _add_crm_organization_fields():
	custom_fields = {
		"CRM Organization": [
			{
				"fieldname": "province",
				"fieldtype": "Link",
				"label": "Tỉnh/TP",
				"options": "CRM Province",
				"insert_after": "website",
			},
			{
				"fieldname": "ward",
				"fieldtype": "Link",
				"label": "Phường/Xã",
				"options": "CRM Ward",
				"insert_after": "province",
			},
			{
				"fieldname": "import_source_id",
				"fieldtype": "Int",
				"label": "Import Source ID",
				"hidden": 1,
				"insert_after": "ward",
			},
		]
	}
	create_custom_fields(custom_fields, ignore_validate=True)


def _add_contact_fields():
	custom_fields = {
		"Contact": [
			{
				"fieldname": "source_lead",
				"fieldtype": "Link",
				"label": "Lead gốc",
				"options": "CRM Lead",
				"insert_after": "last_name",
			},
			{
				"fieldname": "major",
				"fieldtype": "Link",
				"label": "Ngành quan tâm",
				"options": "CRM Major",
				"insert_after": "source_lead",
			},
			{
				"fieldname": "school",
				"fieldtype": "Link",
				"label": "Trường THPT",
				"options": "CRM Organization",
				"insert_after": "major",
			},
			{
				"fieldname": "source",
				"fieldtype": "Data",
				"label": "Nguồn",
				"insert_after": "school",
			},
			{
				"fieldname": "import_source_id",
				"fieldtype": "Int",
				"label": "Import Source ID",
				"hidden": 1,
				"insert_after": "source",
			},
		]
	}
	create_custom_fields(custom_fields, ignore_validate=True)


def _update_lead_side_panel():
	"""Update CRM Lead Side Panel to show enrollment fields and hide legacy sales fields."""
	layout_name = frappe.db.get_value(
		"CRM Fields Layout", {"dt": "CRM Lead", "type": "Side Panel"}, "name"
	)
	if not layout_name:
		return

	layout_doc = frappe.get_doc("CRM Fields Layout", layout_name)
	try:
		sections = json.loads(layout_doc.layout)
	except (json.JSONDecodeError, TypeError):
		return

	fields_to_hide = {
		"annual_revenue", "no_of_employees", "products",
		"industry", "organization", "territory",
	}

	# Side panel layout stores fields nested as section.columns[N].fields (not section.fields)
	for section in sections:
		if not isinstance(section, dict):
			continue
		for column in section.get("columns") or []:
			if not isinstance(column, dict):
				continue
			column["fields"] = [f for f in column.get("fields", []) if f not in fields_to_hide]

	enrollment_fields = [
		"province", "branch", "major", "high_school",
		"ad_channel", "nvfpt", "segments", "tags",
		"conversion_potential", "fpt_aspiration", "source", "lead_owner",
	]

	# Bulk-fetch existing field names to avoid per-field DB queries
	existing_custom = set(frappe.get_all(
		"Custom Field", filters={"dt": "CRM Lead"}, pluck="fieldname"
	))
	existing_docfields = set(frappe.get_all(
		"DocField", filters={"parent": "CRM Lead"}, pluck="fieldname"
	))
	existing_fields = existing_custom | existing_docfields

	# Remove any existing enrollment_section first — makes this idempotent on re-run
	sections = [s for s in sections if s.get("name") != "enrollment_section"]

	valid_fields = [f for f in enrollment_fields if f in existing_fields]
	if valid_fields:
		enrollment_section = {
			"label": "Thông tin tuyển sinh",
			"name": "enrollment_section",
			"opened": True,
			"columns": [{"fields": valid_fields}],
		}
		sections.insert(0, enrollment_section)

	layout_doc.layout = json.dumps(sections)
	layout_doc.save(ignore_permissions=True)
