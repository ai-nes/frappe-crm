import frappe

NEW_ROLES = [
	"Team Leader",
	"Counseller",
	"Sale",
	"CTV-Sale",
	"Promoter-PR",
	"Marketing",
	"Lead Sales",
	"Admissions Director",
	"Administrator",
]

OLD_ROLES = [
	# Old CRM roles
	# Kept during the role-contract migration.  They are explicit aliases for
	# the Sales profile in crm.api.session, not a permission elevation path.
	# A later, approved migration may remove them after account adoption has
	# been audited.
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
	# Frappe utility roles — not needed for CRM
	"Translator",
	"Prepared Report User",
	"Inbox User",
	"Script Manager",
	"Report Manager",
	"Workspace Manager",
	"Dashboard Manager",
]


def create_roles(role_names):
	for role_name in role_names:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 1,
			}).insert(ignore_permissions=True)


def execute():
	# Remove old roles and all their assignments
	for role_name in OLD_ROLES:
		if frappe.db.exists("Role", role_name):
			frappe.db.delete("Has Role", {"role": role_name})
			frappe.delete_doc("Role", role_name, ignore_permissions=True, force=True)

	create_roles(NEW_ROLES)
	frappe.db.commit()
