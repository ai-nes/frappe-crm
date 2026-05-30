# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import csv
import json
import os

import frappe


def execute():
	fixtures_path = os.path.join(frappe.get_app_path("crm"), "migration", "fixtures")
	picklists = _load_picklists(fixtures_path)

	_seed_lead_sources(fixtures_path)
	_seed_lead_statuses(fixtures_path)
	_update_select_options(picklists)

	frappe.db.commit()


def _load_picklists(fixtures_path):
	path = os.path.join(fixtures_path, "picklists.json")
	if not os.path.exists(path):
		frappe.log_error("picklists.json not found — skipping select option seed", "seed_enrollment_picklists")
		return {}
	with open(path, encoding="utf-8") as f:
		return json.load(f)


def _picklist_values(picklists, key):
	return [v for v in picklists.get(key, []) if not v.startswith("_")]


def _seed_lead_sources(fixtures_path):
	csv_path = os.path.join(fixtures_path, "lead_sources.csv")
	if not os.path.exists(csv_path):
		return
	with open(csv_path, newline="", encoding="utf-8") as f:
		for row in csv.DictReader(f):
			name = (row.get("leadsource") or "").strip()
			if not name or frappe.db.exists("CRM Lead Source", name):
				continue
			frappe.get_doc({"doctype": "CRM Lead Source", "source_name": name}).insert(
				ignore_permissions=True
			)


def _seed_lead_statuses(fixtures_path):
	csv_path = os.path.join(fixtures_path, "lead_statuses.csv")
	if not os.path.exists(csv_path):
		return

	# Map by exact status_type column if present; fall back to keyword detection
	status_type_keywords = {
		"mới": "Open", "new": "Open", "chưa liên hệ": "Open",
		"đang xử lý": "Ongoing", "đã liên hệ": "Ongoing",
		"đã chuyển": "Won", "đã nhập học": "Won",
		"không quan tâm": "Lost", "junk": "Lost", "rác": "Lost",
	}

	with open(csv_path, newline="", encoding="utf-8") as f:
		position = 0
		for row in csv.DictReader(f):
			name = (row.get("leadstatus") or "").strip()
			if not name or frappe.db.exists("CRM Lead Status", name):
				continue
			position += 1
			status_type = row.get("status_type") or "Open"
			if not row.get("status_type"):
				for keyword, stype in status_type_keywords.items():
					if keyword in name.lower():
						status_type = stype
						break
			frappe.get_doc(
				{
					"doctype": "CRM Lead Status",
					"lead_status": name,  # autoname field — must match DocType fieldname
					"color": row.get("color") or "gray",
					"type": status_type,
					"position": position,
				}
			).insert(ignore_permissions=True)


def _update_select_options(picklists):
	custom_field_map = {
		"ad_channel": "CRM Lead-ad_channel",
		"fpt_aspiration": "CRM Lead-fpt_aspiration",
		"conversion_potential": "CRM Lead-conversion_potential",
	}
	for key, field_name in custom_field_map.items():
		values = _picklist_values(picklists, key)
		if values and frappe.db.exists("Custom Field", field_name):
			frappe.db.set_value("Custom Field", field_name, "options", "\n".join(values))

	doctype_field_map = {
		"city_type": ("CRM Province", "city_type"),
		"ward_type": ("CRM Ward", "ward_type"),
		"major_group": ("CRM Major", "major_group"),
	}
	for key, (doctype, fieldname) in doctype_field_map.items():
		values = _picklist_values(picklists, key)
		if values:
			frappe.db.set_value(
				"DocField",
				{"parent": doctype, "fieldname": fieldname},
				"options",
				"\n".join(values),
			)
