"""Backfill the normalized School domain before legacy fields are retired."""

from __future__ import annotations

import frappe


def _table_exists(doctype: str) -> bool:
	return bool(frappe.db.table_exists(doctype))


def _column_exists(doctype: str, fieldname: str) -> bool:
	return bool(_table_exists(doctype) and frappe.db.has_column(doctype, fieldname))


def _copy_person_relationships():
	if not _table_exists("CRM School Stakeholder") or not _column_exists("CRM Person", "high_school"):
		return 0
	fields = [
		field
		for field in [
			"name", "full_name", "role", "stakeholder_role", "high_school",
			"relationship_status", "influence", "owner_staff", "owning_team",
		]
		if _column_exists("CRM Person", field)
	]
	rows = frappe.db.sql(
		"select " + ", ".join(f"`{field}`" for field in fields) + " from `tabCRM Person` "
		"where high_school is not null and high_school != ''",
		as_dict=True,
	)
	count = 0
	for row in rows:
		role = row.get("stakeholder_role")
		if not role and row.get("role"):
			role = frappe.db.get_value(
				"CRM Term", {"term_name": row["role"], "category": "stakeholder_role"}, "name"
			)
		if not role:
			role = frappe.db.get_value(
				"CRM Term", {"term_name": "Đầu mối tuyển sinh", "category": "stakeholder_role"}, "name"
			)
		if not role:
			continue
		if frappe.db.exists("CRM School Stakeholder", {"high_school": row.high_school, "person": row.name}):
			continue
		frappe.get_doc(
			{
				"doctype": "CRM School Stakeholder",
				"high_school": row.high_school,
				"person": row.name,
				"stakeholder_role": role,
				"position_title": row.get("role"),
				"relationship_status": row.get("relationship_status") or "New",
				"influence": row.get("influence"),
				"owner_staff": row.get("owner_staff"),
				"owning_team": row.get("owning_team"),
			}
		).insert(ignore_permissions=True)
		count += 1
	return count


def _migrate_activity_stakeholders():
	if not _table_exists("CRM School Stakeholder") or not _column_exists("CRM School Activity", "stakeholder"):
		return 0
	rows = frappe.db.sql(
		"select name, high_school, stakeholder from `tabCRM School Activity` "
		"where stakeholder is not null and stakeholder != ''",
		as_dict=True,
	)
	count = 0
	for row in rows:
		association = frappe.db.get_value(
			"CRM School Stakeholder",
			{"high_school": row.high_school, "person": row.stakeholder},
			"name",
		)
		if association:
			frappe.db.set_value("CRM School Activity", row.name, "stakeholder", association, update_modified=False)
		else:
			frappe.db.set_value("CRM School Activity", row.name, "stakeholder", None, update_modified=False)
		count += 1
	return count


def execute():
	# This patch is intentionally pre_model_sync: create the new association table
	# while the legacy CRM Person fields are still available, then let schema sync
	# retire those fields safely.
	frappe.reload_doc("fcrm", "doctype", "crm_school_stakeholder", force=True)
	if not _table_exists("CRM School Stakeholder"):
		return
	frappe.db.commit()
	_copy_person_relationships()
	_migrate_activity_stakeholders()
	frappe.db.commit()
