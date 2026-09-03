"""Add the Frappe-owned ``risk_tier`` policy field to CRM Action and backfill it.

The tier is a pure function of the Frappe-owned action type (see
``crm.fcrm.student_decision.compute_risk_tier``). Agent-rendered package content
is deliberately not policy input. Unknown types fall back to ``high``.
The column is made ``NOT NULL`` once every row holds a value.

Idempotent / re-runnable: the column add is guarded on
``information_schema.columns`` and the backfill re-derives every row from a
deterministic policy, so a second run is a no-op.

Rollback:
  ``ALTER TABLE `tabCRM Action` MODIFY `risk_tier` varchar(140) NULL;``
  then, if the column itself must go,
  ``ALTER TABLE `tabCRM Action` DROP COLUMN `risk_tier`;``
"""

import frappe

from crm.fcrm.student_decision import compute_risk_tier

_TABLE = "tabCRM Action Item"
_COLUMN = "risk_tier"


def execute():
	if not frappe.db.table_exists("CRM Action Item"):
		return

	frappe.reload_doc("fcrm", "doctype", "crm_action_item")

	if not _column_exists():
		frappe.db.sql_ddl(
			f"ALTER TABLE `{_TABLE}` ADD COLUMN `{_COLUMN}` varchar(140) NOT NULL DEFAULT 'high'"
		)

	# `ADD COLUMN ... NOT NULL DEFAULT 'high'` pre-fills every existing row with
	# the fail-closed default, so the tier must be re-derived for all rows, not
	# just unset ones. The policy is deterministic, so this is a no-op on re-run.
	rows = frappe.db.sql(
		f"SELECT name, action_type, package_seed, `{_COLUMN}` AS current_tier FROM `{_TABLE}`",
		as_dict=True,
	)
	by_tier: dict[str, list[str]] = {"low": [], "mid": [], "high": []}
	for row in rows:
		tier = compute_risk_tier(row.action_type, row.package_seed)
		if tier != row.current_tier:
			by_tier[tier].append(row.name)
	for tier, names in by_tier.items():
		for chunk in (names[i : i + 500] for i in range(0, len(names), 500)):
			placeholders = ", ".join(["%s"] * len(chunk))
			frappe.db.sql(
				f"UPDATE `{_TABLE}` SET `{_COLUMN}` = %s WHERE name IN ({placeholders})",
				(tier, *chunk),
			)

	# Defence in depth: no row may be left unclassified even if the policy
	# helper ever returns something unexpected.
	frappe.db.sql(
		f"UPDATE `{_TABLE}` SET `{_COLUMN}` = 'high' "
		f"WHERE `{_COLUMN}` IS NULL OR `{_COLUMN}` NOT IN ('low', 'mid', 'high')"
	)

	if _column_is_nullable():
		if not frappe.flags.in_test:
			# DDL after the backfill DML would otherwise trip the implicit-commit
			# guard; land the backfill durably first.
			frappe.db.commit()
		frappe.db.sql_ddl(
			f"ALTER TABLE `{_TABLE}` MODIFY `{_COLUMN}` varchar(140) NOT NULL DEFAULT 'high'"
		)

	if not frappe.flags.in_test:
		frappe.db.commit()


def _column_exists() -> bool:
	return bool(
		frappe.db.sql(
			"SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() "
			"AND table_name = %s AND column_name = %s LIMIT 1",
			(_TABLE, _COLUMN),
		)
	)


def _column_is_nullable() -> bool:
	row = frappe.db.sql(
		"SELECT is_nullable FROM information_schema.columns WHERE table_schema = DATABASE() "
		"AND table_name = %s AND column_name = %s LIMIT 1",
		(_TABLE, _COLUMN),
	)
	return bool(row) and row[0][0] == "YES"
