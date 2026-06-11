"""
Add unique indexes on phone (primary) and email (secondary) in CRM Contact.
Skips each index if duplicate data exists (logs a warning instead of crashing migrate).
"""

import frappe


def _add_unique_index(table, column, index_name):
	dupes = frappe.db.sql(
		f"""
		SELECT `{column}`, COUNT(*) as cnt
		FROM `{table}`
		WHERE `{column}` IS NOT NULL AND `{column}` != ''
		GROUP BY `{column}`
		HAVING cnt > 1
		""",
		as_dict=True,
	)
	if dupes:
		dupe_list = ", ".join(str(d[column]) for d in dupes[:5])
		frappe.log_error(
			f"Cannot add unique index on {column}: duplicates exist: {dupe_list}",
			f"add_unique_phone_to_contact patch ({column})",
		)
		return

	existing = frappe.db.sql(
		f"SHOW INDEX FROM `{table}` WHERE Key_name = '{index_name}'",
		as_dict=True,
	)
	if not existing:
		frappe.db.sql(
			f"ALTER TABLE `{table}` ADD UNIQUE INDEX `{index_name}` (`{column}`)"
		)


def execute():
	_add_unique_index("`tabCRM Contact`", "phone", "unique_contact_phone")
	_add_unique_index("`tabCRM Contact`", "email", "unique_contact_email")
