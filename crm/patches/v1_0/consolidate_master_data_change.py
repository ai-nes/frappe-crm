"""Merge change-log and break-glass evidence into one canonical doctype."""

import frappe


TARGET = "CRM Master Data Change"


def _table_exists(doctype):
	return bool(frappe.db.sql("SHOW TABLES LIKE %s", (f"tab{doctype}",)))


def _insert(values):
	if frappe.db.exists(TARGET, values.get("name")):
		return False
	frappe.flags.crm_governance_log_insert = True
	try:
		frappe.get_doc(values).db_insert(ignore_if_duplicate=True)
	finally:
		frappe.flags.crm_governance_log_insert = False
	return True


def _drop(doctype):
	if frappe.db.exists("DocType", doctype):
		frappe.delete_doc("DocType", doctype, ignore_permissions=True, force=True)
	if _table_exists(doctype):
		frappe.db.sql_ddl(f"DROP TABLE `{doctype}`")


def execute():
	if not frappe.db.exists("DocType", TARGET):
		return {"status": "governance_change_pending"}
	normal = 0
	old = "CRM Master Data Change Log"
	if frappe.db.exists("DocType", old) and _table_exists(old):
		rows = frappe.get_all(old, fields="*", order_by="name asc", ignore_permissions=True)
		for row in rows:
			values = dict(row)
			values.update({"doctype": TARGET, "change_kind": "normal"})
			values.pop("creation", None)
			values.pop("modified", None)
			values.pop("modified_by", None)
			if _insert(values):
				normal += 1
		# Approval rows were already nested by Phase 03; make the parent type
		# canonical before dropping the legacy parent table.
		frappe.db.sql("UPDATE `tabCRM Master Data Change Approval` SET parenttype=%s WHERE parenttype=%s", (TARGET, old))
		if frappe.db.count(TARGET, {"change_kind": "normal"}) < len(rows):
			frappe.throw("Governance change migration lost normal change rows")
	break_glass = 0
	old_break_glass = "CRM Master Data Break Glass"
	if frappe.db.exists("DocType", old_break_glass) and _table_exists(old_break_glass):
		rows = frappe.get_all(old_break_glass, fields="*", order_by="name asc", ignore_permissions=True)
		for row in rows:
			values = {
				"doctype": TARGET, "name": row.name, "change_kind": "break_glass",
				"reference_doctype": row.target_doctype, "reference_docname": row.target_docname,
				"action": row.action, "new_value": row.new_value, "status": row.status,
				"reason": row.reason, "proposed_by": row.initiated_by, "proposed_at": row.initiated_at,
				"initiated_by": row.initiated_by, "initiated_at": row.initiated_at,
				"target_version": row.before_version, "nonce_hash": row.nonce_hash,
				"expires_at": row.expires_at, "authorized_by": row.authorized_by,
				"authorized_at": row.authorized_at, "evidence_reference": row.evidence_reference,
				"correlation_id": row.correlation_id, "used_at": row.used_at,
				"reconciliation_id": row.reconciliation_id, "registry_revision": "P9-DEC-002",
			}
			if _insert(values):
				break_glass += 1
		if frappe.db.count(TARGET, {"change_kind": "break_glass"}) < len(rows):
			frappe.throw("Governance change migration lost break-glass rows")
	for source in (old, old_break_glass):
		_drop(source)
	return {"normal": normal, "break_glass": break_glass}
