"""Additive, rerunnable Phase 9 governance/audit preparation patch."""

from __future__ import annotations


GOVERNED_DOCTYPES = (
	"CRM Lead Source",
	"CRM Platform",
	"CRM Term",
	"CRM Campus",
)


def execute():
	try:
		import frappe
	except ImportError as exc:  # pragma: no cover - requires a Frappe bench
		raise RuntimeError("Phase 9 patch requires a Frappe bench") from exc

	for doctype in (*GOVERNED_DOCTYPES, "CRM Master Data Change", "CRM Master Data Change Approval"):
		if frappe.db.exists("DocType", doctype):
			frappe.reload_doc("fcrm", "doctype", frappe.scrub(doctype))

	# Backfill only missing governance metadata. Existing values and historical
	# audit rows are never inferred, renamed or deleted by a site migration.
	from crm.fcrm.governed_reference_registry import config_for

	for doctype in GOVERNED_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		config = config_for(doctype)
		physical = f"tab{doctype}"
		frappe.db.sql(
			f"UPDATE `{physical}` SET owner_role=%s WHERE owner_role IS NULL OR owner_role=''",
			(config["owner_role"],),
		)
		frappe.db.sql(
			f"UPDATE `{physical}` SET approval_state='Approved' WHERE approval_state IS NULL OR approval_state=''",
		)
		frappe.db.sql(
			f"UPDATE `{physical}` SET version=1 WHERE version IS NULL OR version=0",
		)
		frappe.db.sql(
			f"UPDATE `{physical}` SET effective_date=CURDATE() WHERE effective_date IS NULL",
		)

	# This is a new migration, so upgraded sites receive the Phase 9 matrix even
	# though setup_crm_permissions.py was already recorded in patches.txt.
	from crm.patches.v1_0.setup_crm_permissions import apply_managed_docperms

	apply_managed_docperms()
	for doctype in ("CRM Master Data Change", "CRM Master Data Change Approval"):
		frappe.db.delete("DocPerm", {"parent": doctype})
		roles = ("System Manager", "Marketing", "Lead Sales", "Admissions Director")
		for role in roles:
			frappe.get_doc(
				{
					"doctype": "DocPerm",
					"parent": doctype,
					"parenttype": "DocType",
					"parentfield": "permissions",
					"permlevel": 0,
					"role": role,
					"read": 1,
				}
			).insert(ignore_permissions=True)
	frappe.db.commit()

	from crm.fcrm.governance_audit_reconciliation import execute as reconcile

	return reconcile(mode="dry_run")
