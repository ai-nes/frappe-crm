"""Grant Lead Sale delete access to CRM Campaign records."""

import frappe

from crm.patches.v1_0.seed_crm_permission_profiles import execute as seed_permission_profiles
from crm.patches.v1_0.setup_crm_permissions import apply_managed_docperms


def execute():
	if not frappe.db.exists("DocType", "CRM Permission Profile"):
		return

	seed_permission_profiles()
	apply_managed_docperms()
	frappe.clear_cache()
