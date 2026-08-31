"""Merge the small label-only master-data DocTypes into CRM Term."""

from __future__ import annotations

import json

import frappe


TARGET = "CRM Term"
SOURCES = (
	("CRM Lead Status", "status_name", "lead_status"),
	("CRM Lost Reason", "lost_reason", "lost_reason"),
	("CRM Campaign Type", "campaign_type_name", "campaign_type"),
	("CRM Intent Type", "intent_type_name", "intent_type"),
	("CRM Interaction Type", "interaction_type_name", "interaction_type"),
	("CRM School Type", "school_type_name", "school_type"),
	("CRM Major Group", "group_name", "major_group"),
	("CRM Aspiration", "aspiration_name", "aspiration"),
	("CRM Region", "region_name", "region"),
	("CRM Enrollment Status", "status_name", "enrollment_status"),
)

REFERENCE_FIELDS = {
	"lead_status": (("CRM Contact", "lead_status"),),
	"lost_reason": (("CRM Lead", "lost_reason"), ("CRM Deal", "lost_reason")),
	"campaign_type": (("CRM Campaign", "campaign_type"),),
	"intent_type": (("CRM Intent", "intent_type"), ("CRM Score Signal", "intent_type")),
	"interaction_type": (("CRM Interaction", "interaction_type"),),
	"school_type": (("CRM High School", "school_type"),),
	"major_group": (("CRM Major", "major_group"),),
	"aspiration": (("CRM Contact", "aspiration"), ("CRM Student", "aspiration")),
	"region": (("CRM Province", "region"),),
	"enrollment_status": (("CRM Contact", "enrollment_status"), ("CRM Student", "enrollment_status")),
}


def execute():
	if not frappe.db.exists("DocType", TARGET):
		frappe.throw(f"{TARGET} DocType is missing; run model sync before this patch")
	before = {}
	for source, name_field, category in SOURCES:
		rows = frappe.get_all(source, fields="*", order_by="name asc") if frappe.db.exists("DocType", source) else []
		before[category] = len(rows)
		for row in rows:
			target_name = row.name
			existing_category = frappe.db.get_value(TARGET, row.name, "category") if frappe.db.exists(TARGET, row.name) else None
			if existing_category == category:
				continue
			if existing_category and existing_category != category:
				target_name = f"{category}:{row.name}"
			metadata = {key: row.get(key) for key in row if key not in {"name", "owner", "creation", "modified", "modified_by", "docstatus", name_field}}
			values = {"doctype": TARGET, "name": target_name, "term_name": row.get(name_field) or row.name, "category": category, "owner_role": row.get("owner_role"), "is_active": 1, "sort_order": row.get("position") or row.get("stage_order") or 0, "metadata": json.dumps(metadata, default=str), "description": row.get("description") or row.get("description_vi")}
			frappe.flags.crm_term_migration = True
			try:
				frappe.get_doc(values).db_insert(ignore_if_duplicate=True)
			finally:
				frappe.flags.crm_term_migration = False
			for consumer, field in REFERENCE_FIELDS[category]:
				if frappe.db.exists("DocType", consumer) and frappe.db.has_column(consumer, field) and target_name != row.name:
					frappe.db.set_value(consumer, {field: row.name}, field, target_name, update_modified=False)
	for source, name_field, category in SOURCES:
		if frappe.db.exists("DocType", source):
			for row in frappe.get_all(source, fields=["name", name_field]):
				if not frappe.db.exists(TARGET, {"term_name": row.get(name_field), "category": category}):
					frappe.throw(f"CRM Term migration lost {source} row {row.name}")
	for source, _, _ in SOURCES:
		if frappe.db.exists("DocType", source):
			frappe.delete_doc("DocType", source, ignore_permissions=True, force=True)
		table = f"tab{source}"
		if frappe.db.sql("SHOW TABLES LIKE %s", (table,)):
			frappe.db.sql_ddl(f"DROP TABLE `{table}`")
	return {"before": before, "dropped": [source for source, _, _ in SOURCES]}
