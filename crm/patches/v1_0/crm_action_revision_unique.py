"""Add the atomic Action Revision uniqueness fence used by Workbench edits."""
import frappe


def execute():
	if not frappe.db.exists("DocType", "CRM Action Revision"):
		return
	rows = frappe.db.sql(
		"""select action, revision, min(name) keep_name from `tabCRM Action Revision`
		where action is not null group by action, revision having count(*) > 1""",
		as_dict=True,
	)
	if rows:
		frappe.throw("CRM Action Revision has duplicate action/revision rows; resolve them before enabling the unique fence.")
	index = "crm_action_revision_action_revision_uniq"
	existing = frappe.db.sql("show indexes from `tabCRM Action Revision` where Key_name=%s", index)
	if not existing:
		frappe.db.sql(f"alter table `tabCRM Action Revision` add unique index `{index}` (`action`, `revision`)")
