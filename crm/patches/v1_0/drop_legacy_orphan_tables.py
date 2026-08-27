"""Drop physical tables left behind by completed technical migrations."""

from __future__ import annotations

import frappe

ORPHAN_TABLES = (
	"tabCRM Sales Action",
	"tabCRM Student Task",
	"tabCRM Student Task Revision",
	"tabCRM Note",
)


def execute():
	dropped = []
	for table in ORPHAN_TABLES:
		if frappe.db.sql("SHOW TABLES LIKE %s", (table,)):
			frappe.db.sql_ddl(f"DROP TABLE `{table}`")
			dropped.append(table)
	return {"dropped": dropped, "missing": [table for table in ORPHAN_TABLES if table not in dropped]}
