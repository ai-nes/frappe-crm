import frappe

NEW_ROLES = [
	"Team Leader",
	"Counseller",
	"Sale",
	"CTV-Sale",
	"Promoter-PR",
	"Administrator",
]

OLD_ROLES = [
	# Old CRM roles
	"Sales Manager",
	"Sales User",
	# ERPNext business roles — irrelevant on a CRM-only deployment
	"Accounts Manager",
	"Accounts User",
	"Purchase Manager",
	"Purchase User",
	"Purchase Master Manager",
	"Sales Master Manager",
	"Maintenance Manager",
	"Maintenance User",
	"Stock Manager",
	"Stock User",
	"HR Manager",
	"HR User",
	"Manufacturing Manager",
	"Manufacturing User",
	"Projects Manager",
	"Projects User",
	"Expense Approver",
	"Leave Approver",
	"Shift Request Approver",
	"Quality Manager",
	"Item Manager",
	"Auditor",
	# Frappe content roles — not needed for CRM
	"Blogger",
	"Newsletter Manager",
	"Knowledge Base Editor",
	"Knowledge Base Contributor",
	"Website Manager",
]


def execute():
	# Remove old roles and all their assignments
	for role_name in OLD_ROLES:
		if frappe.db.exists("Role", role_name):
			frappe.db.delete("Has Role", {"role": role_name})
			frappe.delete_doc("Role", role_name, ignore_permissions=True, force=True)

	# Create new roles
	for role_name in NEW_ROLES:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 1,
			}).insert(ignore_permissions=True)

	frappe.db.commit()
