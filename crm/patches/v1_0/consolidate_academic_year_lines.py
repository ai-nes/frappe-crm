"""Merge academic-year policy child tables into CRM Academic Year Line."""

import frappe


def _table_exists(doctype):
	return bool(frappe.db.sql("SHOW TABLES LIKE %s", (f"tab{doctype}",)))


def _copy(source, kind, fields):
	if not frappe.db.exists("DocType", source) or not _table_exists(source):
		return 0
	rows = frappe.get_all(source, fields=["name", "parent", "parenttype", "idx", *fields], order_by="parent asc, idx asc", ignore_permissions=True)
	for row in rows:
		values = {"doctype": "CRM Academic Year Line", "name": row.name, "parent": row.parent, "parenttype": row.parenttype, "parentfield": "lines", "idx": row.idx, "line_kind": kind}
		values.update({field: row.get(field) for field in fields})
		frappe.get_doc(values).db_insert(ignore_if_duplicate=True)
	actual = frappe.db.count("CRM Academic Year Line", {"line_kind": kind, "parenttype": "CRM Academic Year Config"})
	if actual < len(rows):
		frappe.throw(f"Academic line migration lost {source} rows: expected at least {len(rows)}, found {actual}")
	return len(rows)


def _drop(source):
	if frappe.db.exists("DocType", source):
		frappe.delete_doc("DocType", source, ignore_permissions=True, force=True)
	if _table_exists(source):
		frappe.db.sql_ddl(f"DROP TABLE `{source}`")


def execute():
	if not frappe.db.exists("DocType", "CRM Academic Year Line"):
		return {"status": "academic_line_pending"}
	counts = {
		"tuition": _copy("CRM Tuition Policy Item", "tuition", ["major", "campus", "amount", "note"]),
		"scholarship": _copy("CRM Scholarship Item", "scholarship", ["scholarship_name", "amount", "criteria"]),
		"quota": _copy("CRM Quota Item", "quota", ["major", "campus", "quota"]),
	}
	for source in ("CRM Tuition Policy Item", "CRM Scholarship Item", "CRM Quota Item"):
		_drop(source)
	return counts
