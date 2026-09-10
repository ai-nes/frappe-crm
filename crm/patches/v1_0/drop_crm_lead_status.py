"""Retire the obsolete CRM Lead Status vocabulary and Contact field."""

from __future__ import annotations

import json

import frappe


LAYOUTS = (
	"CRM Student-Quick Entry",
	"CRM Student-Side Panel",
	"CRM Student-Data Fields",
)


def _without_lead_status(value):
	if isinstance(value, dict):
		return {key: _without_lead_status(item) for key, item in value.items()}
	if isinstance(value, list):
		return [item for item in (_without_lead_status(item) for item in value) if item != "lead_status"]
	return value


def _remove_contact_layout_field() -> None:
	if not frappe.db.table_exists("Fields Layout"):
		return
	for name in LAYOUTS:
		layout = frappe.db.get_value("Fields Layout", name, "layout")
		if not layout:
			continue
		cleaned = _without_lead_status(frappe.parse_json(layout))
		frappe.db.set_value(
			"Fields Layout",
			name,
			"layout",
			json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")),
			update_modified=False,
		)


def execute() -> None:
	if frappe.db.exists("DocType", "CRM Lead Status"):
		frappe.delete_doc("DocType", "CRM Lead Status", force=True, ignore_permissions=True)
	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabCRM Lead Status`")

	if frappe.db.table_exists("CRM Student"):
		columns = {row[0] for row in frappe.db.sql("SHOW COLUMNS FROM `tabCRM Student`")}
		if "lead_status" in columns:
			frappe.db.sql_ddl("ALTER TABLE `tabCRM Student` DROP COLUMN `lead_status`")

	_remove_contact_layout_field()
	# The workspace source changed together with the retired vocabularies, but
	# upgrades do not run install hooks. Reload it here so old CRM Term/Lead
	# Status links cannot remain in Desk metadata.
	frappe.reload_doc("fcrm", "Workspace", "Frappe CRM", force=True)
	frappe.clear_cache(doctype="CRM Student")
	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()
