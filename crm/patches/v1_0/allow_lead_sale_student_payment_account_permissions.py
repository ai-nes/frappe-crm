"""Grant Lead Sale access to the bank details edited from Student profiles.

The payment account DocType is intentionally separate from CRM Student.  The
Lead Sale profile can update the submitted account details through the Student
profile API.  Re-seeding and syncing here updates existing sites without a
manual DocPerm edit.
"""

import frappe

from crm.patches.v1_0.seed_crm_permission_profiles import execute as seed_permission_profiles
from crm.patches.v1_0.setup_crm_permissions import apply_managed_docperms


def execute():
	if not frappe.db.exists("DocType", "CRM Student Payment Account"):
		return

	seed_permission_profiles()
	apply_managed_docperms()
	frappe.clear_cache(doctype="CRM Student Payment Account")
