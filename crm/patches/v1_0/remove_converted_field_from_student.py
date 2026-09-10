import frappe


def execute():
	# Migrate students with converted=1 but no enrollment_status set to CONVERTED.
	frappe.db.sql("""
		UPDATE `tabCRM Lead`
		SET enrollment_status = 'CONVERTED'
		WHERE converted = 1
		  AND (enrollment_status IS NULL OR enrollment_status = '')
	""")

	# Drop the column if it still exists (DDL requires commit first to avoid ImplicitCommitError)
	if frappe.db.has_column("CRM Lead", "converted"):
		frappe.db.commit()
		frappe.db.sql("ALTER TABLE `tabCRM Lead` DROP COLUMN `converted`")
