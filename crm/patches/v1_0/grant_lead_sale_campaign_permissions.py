"""Grant Lead Sale create/update access to acquisition records.

The campaign DocType fixture already declares the intended Lead Sale grant, but
sites that ran the DB-backed permission policy previously received a read-only
DocPerm row from the old acquisition matrix. Re-seed the canonical profiles and
sync managed DocPerm rows so existing sites converge without a manual DB edit.
"""

import frappe

from crm.patches.v1_0.seed_crm_permission_profiles import execute as seed_permission_profiles
from crm.patches.v1_0.setup_crm_permissions import apply_managed_docperms


def execute():
	if not frappe.db.exists("DocType", "CRM Permission Profile"):
		return

	seed_permission_profiles()
	apply_managed_docperms()
	frappe.clear_cache()
