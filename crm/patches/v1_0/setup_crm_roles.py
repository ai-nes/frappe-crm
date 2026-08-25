import frappe

from crm.fcrm.role_policy import CRM_POLICY_ROLE_NAMES

NEW_ROLES = list(CRM_POLICY_ROLE_NAMES)

OLD_ROLES = [
	# Old CRM roles
	# Kept during the role-contract migration. They are explicit aliases for
	# canonical CRM profiles, not a permission elevation path. The retired
	# duplicate ``Sales`` role is intentionally excluded from this catalog.
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
	"Enrollment Manager",
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
	"Report Manager",
	"Workspace Manager",
	"Dashboard Manager",
]


def create_roles(role_names):
	for role_name in role_names:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc(
				{
					"doctype": "Role",
					"role_name": role_name,
					"desk_access": 1,
				}
			).insert(ignore_permissions=True)


def execute():
	# Alias retirement is a future, audit-gated migration. This setup patch must
	# only ensure policy roles exist; it never deletes a role or assignment.
	create_roles(NEW_ROLES)
