"""Forward-only database adapter for the Phase 2 role policy.

Historical patches may already have run, so this patch updates only live DocPerm
rows. It never reloads a DocType or writes source fixtures.
"""

import frappe

from crm.fcrm.role_policy import CRM_POLICY_ROLE_NAMES
from crm.patches.v1_0.setup_crm_permissions import apply_managed_docperms
from crm.patches.v1_0.setup_crm_roles import create_roles


def execute():
	"""Apply the Phase 2 policy in the surrounding migration transaction."""
	frappe.db.savepoint("phase2_role_policy")
	try:
		create_roles(CRM_POLICY_ROLE_NAMES)
		apply_managed_docperms()
		# This governed-workflow support DocType is not in the managed matrix, but
		# the retired migration-only role must not retain authority through it.
		frappe.db.delete("DocPerm", {"parent": "CRM Master Data Change", "role": "CRM Data Steward"})
	except Exception:
		frappe.db.rollback(save_point="phase2_role_policy")
		raise
	frappe.clear_cache()
