"""Add the durable NBA dirty marker used by the hourly student sweep."""

import frappe

_TABLE = "tabCRM Student"
_DIRTY_INDEX = "crm_student_nba_dirty_since_idx"


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_student")
	if not frappe.db.table_exists("CRM Student"):
		return

	if not _index_exists(_DIRTY_INDEX):
		frappe.db.sql_ddl(f"ALTER TABLE `{_TABLE}` ADD INDEX `{_DIRTY_INDEX}` (`nba_dirty_since`)")

	if not frappe.flags.in_test:
		frappe.db.commit()


def _index_exists(index_name: str) -> bool:
	return bool(
		frappe.db.sql(
			"SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() "
			"AND table_name = %s AND index_name = %s LIMIT 1",
			(_TABLE, index_name),
		)
	)
