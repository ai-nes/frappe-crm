import frappe

from crm.patches.v1_0.setup_crm_roles import create_roles

NEW_ROLES = [
	"Marketing Operator",
	"Marketing Lead",
	"Admissions Operations",
	"Admissions Director",
]


def execute():
	create_roles(NEW_ROLES)
	frappe.db.commit()
