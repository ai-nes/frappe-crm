"""Fold province mappings into CRM Province.previous_names and drop the old table."""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.exists("DocType", "CRM Province Former Name"):
		return {"migrated": 0, "skipped": 0}
	has_doctype = frappe.db.exists("DocType", "CRM Province Mapping")
	has_table = bool(frappe.db.sql("SHOW TABLES LIKE %s", ("tabCRM Province Mapping",)))
	if not has_table:
		return {"migrated": 0, "skipped": 0}
	rows = (
		frappe.get_all("CRM Province Mapping", fields=["name", "old_province", "new_province"], order_by="name asc")
		if has_doctype
		else frappe.db.sql("select name, old_province, new_province from `tabCRM Province Mapping` order by name asc", as_dict=True)
	)
	migrated = skipped = 0
	for row in rows:
		parent = row.new_province if frappe.db.exists("CRM Province", row.new_province) else frappe.db.get_value("CRM Province", {"province_name": row.new_province}, "name")
		if not parent:
			skipped += 1
			continue
		if not frappe.db.exists("CRM Province Former Name", {"parent": parent, "parentfield": "previous_names", "former_name": row.old_province}):
			province = frappe.get_doc("CRM Province", parent)
			province.append("previous_names", {"former_name": row.old_province})
			province.save(ignore_permissions=True)
		migrated += 1
	if skipped:
		frappe.throw(f"Province mapping migration could not resolve {skipped} target province rows")
	if frappe.db.exists("DocType", "CRM Province Mapping"):
		frappe.delete_doc("DocType", "CRM Province Mapping", ignore_permissions=True, force=True)
	if frappe.db.table_exists("CRM Province Mapping"):
		frappe.db.sql_ddl("DROP TABLE `tabCRM Province Mapping`")
	return {"before": len(rows), "migrated": migrated, "skipped": skipped, "after": migrated}
