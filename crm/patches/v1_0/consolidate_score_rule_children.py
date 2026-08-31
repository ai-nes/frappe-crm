"""Move negative and time-decay child rows into CRM Score Rule."""

import frappe


def _table_exists(doctype):
	return bool(frappe.db.sql("SHOW TABLES LIKE %s", (f"tab{doctype}",)))


def _copy_rows(source, kind, fields):
	if not frappe.db.exists("DocType", source) or not _table_exists(source):
		return 0
	rows = frappe.get_all(source, fields=["name", "parent", "parenttype", "idx", *fields], order_by="parent asc, idx asc", ignore_permissions=True)
	for row in rows:
		values = {"doctype": "CRM Score Rule", "name": row.name, "parent": row.parent, "parenttype": row.parenttype, "parentfield": "rules", "idx": row.idx, "rule_kind": kind}
		values.update({field: row.get(field) for field in fields})
		frappe.get_doc(values).db_insert(ignore_if_duplicate=True)
	actual = frappe.db.count("CRM Score Rule", {"rule_kind": kind, "parenttype": "CRM Score Template"})
	if actual < len(rows):
		frappe.throw(f"Score rule migration lost {source} rows: expected at least {len(rows)}, found {actual}")
	return len(rows)


def _drop(source):
	if frappe.db.exists("DocType", source):
		frappe.delete_doc("DocType", source, ignore_permissions=True, force=True)
	if _table_exists(source):
		frappe.db.sql_ddl(f"DROP TABLE `tab{source}`")


def execute():
	if not frappe.db.exists("DocType", "CRM Score Rule"):
		return {"status": "score_rule_pending"}
	frappe.db.sql("UPDATE `tabCRM Score Rule` SET rule_kind = 'positive' WHERE rule_kind IS NULL OR rule_kind = ''")
	negative = _copy_rows("CRM Negative Score Rule", "negative", ["signal", "is_active", "penalty_amount", "cooldown_days", "max_penalties"])
	decay = _copy_rows("CRM Time Decay Config", "time_decay", ["max_days", "multiplier", "tier_label"])
	for source in ("CRM Negative Score Rule", "CRM Time Decay Config"):
		_drop(source)
	return {"negative": negative, "time_decay": decay}
