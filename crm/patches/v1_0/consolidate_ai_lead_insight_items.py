"""Merge the three AI insight child tables into one discriminated table."""

import frappe


def _table_exists(doctype):
	return bool(frappe.db.sql("SHOW TABLES LIKE %s", (f"tab{doctype}",)))


def _copy(source, kind, fields):
	if not frappe.db.exists("DocType", source) or not _table_exists(source):
		return 0
	rows = frappe.get_all(source, fields=["name", "parent", "parenttype", "idx", *fields], order_by="parent asc, idx asc", ignore_permissions=True)
	for row in rows:
		values = {"doctype": "CRM AI Lead Insight Item", "name": row.name, "parent": row.parent, "parenttype": row.parenttype, "parentfield": "items", "idx": row.idx, "item_kind": kind}
		values.update({field: row.get(field) for field in fields})
		frappe.get_doc(values).db_insert(ignore_if_duplicate=True)
	actual = frappe.db.count("CRM AI Lead Insight Item", {"item_kind": kind, "parenttype": "CRM AI Lead Insight"})
	if actual < len(rows):
		frappe.throw(f"AI insight migration lost {source} rows: expected at least {len(rows)}, found {actual}")
	return len(rows)


def _drop(source):
	if frappe.db.exists("DocType", source):
		frappe.delete_doc("DocType", source, ignore_permissions=True, force=True)
	if _table_exists(source):
		frappe.db.sql_ddl(f"DROP TABLE `tab{source}`")


def execute():
	if not frappe.db.exists("DocType", "CRM AI Lead Insight Item"):
		return {"status": "ai_item_pending"}
	counts = {
		"interest": _copy("CRM AI Lead Insight Interest", "interest", ["dimension_code", "label", "interest_level", "score", "trend", "stance", "confidence", "is_current", "evidence"]),
		"objection": _copy("CRM AI Lead Insight Objection", "objection", ["label", "confidence", "evidence"]),
		"risk": _copy("CRM AI Lead Insight Risk Flag", "risk", ["label", "severity", "evidence"]),
	}
	for source in ("CRM AI Lead Insight Interest", "CRM AI Lead Insight Objection", "CRM AI Lead Insight Risk Flag"):
		_drop(source)
	return counts
