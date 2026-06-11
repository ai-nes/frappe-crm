import frappe

NEW_STATUSES = ["New", "Pending Confirmation", "Confirmed", "Prospect", "Enrolled", "Refused", "Converted"]


def execute():
	for name in NEW_STATUSES:
		if not frappe.db.exists("CRM Enrollment Status", name):
			frappe.get_doc({
				"doctype": "CRM Enrollment Status",
				"status_name": name,
			}).insert(ignore_permissions=True)

	# Clear stale values from old Select field that don't match new Link records
	frappe.db.sql("""
		UPDATE `tabCRM Student`
		SET enrollment_status = NULL
		WHERE enrollment_status IS NOT NULL
		  AND enrollment_status NOT IN %(statuses)s
	""", {"statuses": NEW_STATUSES})

	frappe.db.commit()
