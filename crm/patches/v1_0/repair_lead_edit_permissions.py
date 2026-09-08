"""Repair persisted Lead edit access after the scoped permission rollout.

Existing sites can have the correct DocPerm rows but stale ownership projections.
The row-level permission hook uses ``owner_staff`` and ``owning_team`` to decide
whether Sale, Lead Sale, and CTV Sale may edit a Lead, so both the permission
catalogue and legacy Lead ownership fields must be brought back in sync.
"""

import frappe


def execute():
	from crm.patches.v1_0.backfill_owner_fields_from_assigned_to import (
		execute as backfill_owner_fields,
	)
	from crm.patches.v1_0.seed_new_lead_role_profiles import execute as seed_role_profiles

	seed_role_profiles()
	backfill_owner_fields()
	frappe.clear_cache()
