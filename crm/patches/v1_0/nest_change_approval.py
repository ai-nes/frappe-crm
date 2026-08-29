"""Convert master-data approvals in place to children of their change log."""

from __future__ import annotations

import frappe

DOCTYPE = "CRM Master Data Change Approval"


def execute():
	if not frappe.db.exists("DocType", "CRM Master Data Change Log"):
		return {"status": "governance_change_pending"}
	if not frappe.db.table_exists(DOCTYPE):
		return {"migrated": 0}
	before_total = frappe.db.count(DOCTYPE)
	if not frappe.db.has_column(DOCTYPE, "change_log"):
		remaining = frappe.db.count(DOCTYPE, {"parentfield": "approvals"})
		if remaining != before_total:
			frappe.throw(f"Master-data approval nesting incomplete after cutover: expected {before_total}, found {remaining}")
		return {"before": before_total, "migrated": 0, "after": before_total, "remaining": 0, "status": "already_nested"}
	rows = frappe.db.sql(
		"""select name, change_log, creation
		from `tabCRM Master Data Change Approval`
		where change_log is not null
		order by change_log asc, creation asc, name asc""",
		as_dict=True,
	)
	invalid = frappe.db.sql(
		"""select name from `tabCRM Master Data Change Approval`
		where (change_log is null or change_log = '') and (parent is null or parent = '')""",
		as_dict=True,
	)
	if invalid:
		frappe.throw(f"Master-data approval migration found orphan rows: {', '.join(row.name for row in invalid[:20])}")
	mismatched = frappe.db.sql(
		"""select name from `tabCRM Master Data Change Approval`
		where change_log is not null and parent is not null and parent != change_log""",
		as_dict=True,
	)
	if mismatched:
		frappe.throw(f"Master-data approval migration found mismatched parents: {', '.join(row.name for row in mismatched[:20])}")
	missing_changes = [row.change_log for row in rows if not frappe.db.exists("CRM Master Data Change Log", row.change_log)]
	if missing_changes:
		frappe.throw(f"Master-data approval migration found missing change logs: {', '.join(sorted(set(missing_changes)))}")
	duplicates = frappe.db.sql(
		"""select change_log, approval_role from `tabCRM Master Data Change Approval`
		where change_log is not null and change_log != ''
		group by change_log, approval_role having count(*) > 1""",
		as_dict=True,
	)
	if duplicates:
		frappe.throw("Master-data approval migration found duplicate approval roles")
	idx_by_parent = {}
	for row in rows:
		idx_by_parent[row.change_log] = idx_by_parent.get(row.change_log, 0) + 1
		frappe.db.sql(
			"""update `tabCRM Master Data Change Approval`
			set parent=%s, parenttype=%s, parentfield=%s, idx=%s
			where name=%s""",
			(row.change_log, "CRM Master Data Change Log", "approvals", idx_by_parent[row.change_log], row.name),
		)
	remaining = frappe.db.sql(
		"""select count(*) from `tabCRM Master Data Change Approval`
		where change_log is not null and (parent is null or parent = '')"""
	)[0][0]
	if remaining:
		frappe.throw(f"Master-data approval nesting incomplete: {remaining} rows remain")
	after_total = frappe.db.count(DOCTYPE)
	if after_total != before_total:
		frappe.throw(f"Master-data approval count changed during nesting: before={before_total}, after={after_total}")
	if frappe.db.has_column(DOCTYPE, "change_log"):
		frappe.db.sql_ddl("ALTER TABLE `tabCRM Master Data Change Approval` DROP COLUMN `change_log`")
	return {"before": before_total, "migrated": len(rows), "after": after_total, "remaining": 0}
