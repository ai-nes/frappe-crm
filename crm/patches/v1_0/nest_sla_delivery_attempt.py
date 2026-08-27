"""Convert SLA delivery attempts in place to children of their delivery."""

from __future__ import annotations

import frappe

DOCTYPE = "CRM Student SLA Delivery Attempt"


def execute():
	if not frappe.db.table_exists(DOCTYPE):
		return {"migrated": 0}
	before_total = frappe.db.count(DOCTYPE)
	if not frappe.db.has_column(DOCTYPE, "delivery"):
		remaining = frappe.db.count(DOCTYPE, {"parentfield": "attempts"})
		if remaining != before_total:
			frappe.throw(f"SLA delivery attempt nesting incomplete after cutover: expected {before_total}, found {remaining}")
		return {"before": before_total, "migrated": 0, "after": before_total, "remaining": 0, "status": "already_nested"}
	rows = frappe.db.sql(
		"""select name, delivery, attempt_number
		from `tabCRM Student SLA Delivery Attempt`
		where delivery is not null
		order by delivery asc, attempt_number asc, creation asc, name asc""",
		as_dict=True,
	)
	invalid = frappe.db.sql(
		"""select name from `tabCRM Student SLA Delivery Attempt`
		where (delivery is null or delivery = '') and (parent is null or parent = '')""",
		as_dict=True,
	)
	if invalid:
		frappe.throw(f"SLA delivery attempt migration found orphan rows: {', '.join(row.name for row in invalid[:20])}")
	mismatched = frappe.db.sql(
		"""select name from `tabCRM Student SLA Delivery Attempt`
		where delivery is not null and parent is not null and parent != delivery""",
		as_dict=True,
	)
	if mismatched:
		frappe.throw(f"SLA delivery attempt migration found mismatched parents: {', '.join(row.name for row in mismatched[:20])}")
	if rows:
		missing_deliveries = [row.delivery for row in rows if not frappe.db.exists("CRM Student SLA Delivery", row.delivery)]
		if missing_deliveries:
			frappe.throw(f"SLA delivery attempt migration found missing deliveries: {', '.join(sorted(set(missing_deliveries)))}")
	duplicates = frappe.db.sql(
		"""select provider_submission_key from `tabCRM Student SLA Delivery Attempt`
		where provider_submission_key is not null and provider_submission_key != ''
		group by provider_submission_key having count(*) > 1""",
		as_dict=True,
	)
	if duplicates:
		frappe.throw("SLA delivery attempt migration found duplicate provider submission keys")
	idx_by_parent = {}
	for row in rows:
		idx_by_parent[row.delivery] = idx_by_parent.get(row.delivery, 0) + 1
		frappe.db.sql(
			"""update `tabCRM Student SLA Delivery Attempt`
			set parent=%s, parenttype=%s, parentfield=%s, idx=%s
			where name=%s""",
			(row.delivery, "CRM Student SLA Delivery", "attempts", idx_by_parent[row.delivery], row.name),
		)
	remaining = frappe.db.sql(
		"""select count(*) from `tabCRM Student SLA Delivery Attempt`
		where delivery is not null and (parent is null or parent = '')"""
	)[0][0]
	if remaining:
		frappe.throw(f"SLA delivery attempt nesting incomplete: {remaining} rows remain")
	after_total = frappe.db.count(DOCTYPE)
	if after_total != before_total:
		frappe.throw(f"SLA delivery attempt count changed during nesting: before={before_total}, after={after_total}")
	if frappe.db.has_column(DOCTYPE, "delivery"):
		frappe.db.sql_ddl("ALTER TABLE `tabCRM Student SLA Delivery Attempt` DROP COLUMN `delivery`")
	return {"before": before_total, "migrated": len(rows), "after": after_total, "remaining": 0}
