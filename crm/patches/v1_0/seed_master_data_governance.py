import frappe
from frappe.utils import nowdate

from crm.patches.v1_0 import setup_crm_permissions
from crm.patches.v1_0.setup_crm_roles import create_roles

GOVERNED_DOCTYPES = {
	"CRM Lead Source": "Marketing",
	"CRM Platform": "Marketing",
	"CRM Term": "Lead Sales",
	"CRM Campus": "Admissions Director",
}


def execute():
	for doctype in ["CRM Lead Source", "CRM Platform", "CRM Term", "CRM Campus", "CRM Master Data Change"]:
		frappe.reload_doc("fcrm", "doctype", frappe.scrub(doctype))

	# Re-run permission setup so the 5 governed doctypes pick up the owner/approver
	# roles added to setup_crm_permissions.MARKETING_LOOKUP_PERMS/LOST_REASON_PERMS/
	# CAMPUS_PERMS -- setup_crm_permissions already ran once (patches.txt, earlier)
	# on any existing site, so its old permission JSON is otherwise stuck as-is.
	setup_crm_permissions.execute()

	for doctype in GOVERNED_DOCTYPES:
		# One batched UPDATE per backfilled field (WHERE field is unset), not a
		# get_all + per-row set_value loop -- avoids the N+1 pattern already
		# flagged and fixed in Phase 6.
		frappe.db.sql(
			f"""
			UPDATE `tab{doctype}`
			SET owner_role = %(owner_role)s
			WHERE owner_role IS NULL OR owner_role = ''
			""",
			{"owner_role": GOVERNED_DOCTYPES[doctype]},
		)
		frappe.db.sql(
			f"""
			UPDATE `tab{doctype}`
			SET approval_state = 'Approved'
			WHERE approval_state IS NULL OR approval_state = ''
			"""
		)
		frappe.db.sql(
			f"""
			UPDATE `tab{doctype}`
			SET version = 1
			WHERE version IS NULL OR version = 0
			"""
		)
		frappe.db.sql(
			f"""
			UPDATE `tab{doctype}`
			SET effective_date = %(effective_date)s
			WHERE effective_date IS NULL
			""",
			{"effective_date": nowdate()},
		)

	frappe.db.commit()
