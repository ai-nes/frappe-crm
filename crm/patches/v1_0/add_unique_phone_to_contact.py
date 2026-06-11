"""
Add unique index on phone in CRM Contact.
Phone is the primary identifier for a contact — duplicates cause data confusion.
Skips if duplicate data exists (logs a warning instead of crashing migrate).
"""

import frappe


def execute():
	# Check for existing duplicates before adding constraint
	dupes = frappe.db.sql(
		"""
		SELECT phone, COUNT(*) as cnt
		FROM `tabCRM Contact`
		WHERE phone IS NOT NULL AND phone != ''
		GROUP BY phone
		HAVING cnt > 1
		""",
		as_dict=True,
	)
	if dupes:
		dupe_list = ", ".join(d.phone for d in dupes[:5])
		frappe.log_error(
			f"Cannot add unique phone index: duplicate phones exist: {dupe_list}",
			"add_unique_phone_to_contact patch",
		)
		return

	# Check if index already exists
	existing = frappe.db.sql(
		"SHOW INDEX FROM `tabCRM Contact` WHERE Key_name = 'unique_contact_phone'",
		as_dict=True,
	)
	if not existing:
		frappe.db.sql(
			"ALTER TABLE `tabCRM Contact` ADD UNIQUE INDEX `unique_contact_phone` (`phone`)"
		)
