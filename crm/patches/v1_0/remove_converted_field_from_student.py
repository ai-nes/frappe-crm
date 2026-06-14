import frappe


def execute():
	# Migrate students with converted=1 but no enrollment_status set to "Đã chuyển đổi"
	frappe.db.sql("""
		UPDATE `tabCRM Student`
		SET enrollment_status = 'Đã chuyển đổi'
		WHERE converted = 1
		  AND (enrollment_status IS NULL OR enrollment_status = '')
	""")

	# Drop the column if it still exists (DDL requires commit first to avoid ImplicitCommitError)
	if frappe.db.has_column("CRM Student", "converted"):
		frappe.db.commit()
		frappe.db.sql("ALTER TABLE `tabCRM Student` DROP COLUMN `converted`")
