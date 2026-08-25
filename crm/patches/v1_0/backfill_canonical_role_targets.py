"""Move unambiguous legacy CRM roles to the approved canonical targets."""

import frappe

from crm.api.user import set_canonical_crm_profile
from crm.fcrm.role_policy import ROLE_BACKFILL_SOURCES, backfill_target_for_roles


def execute():
	"""Backfill one target only; leave conflicting accounts for controlled review."""
	result = {"migrated": [], "conflicts": []}
	for user in frappe.get_all("User", filters={"enabled": 1}, pluck="name"):
		if user in {"Administrator", "Guest"}:
			continue
		roles = set(frappe.get_roles(user))
		sources = roles & ROLE_BACKFILL_SOURCES
		if not sources:
			continue
		target = backfill_target_for_roles(roles)
		if not target or "System Manager" in roles:
			result["conflicts"].append(user)
			continue
		user_doc = frappe.get_doc("User", user)
		set_canonical_crm_profile(user_doc, target)
		user_doc.save(ignore_permissions=True)
		result["migrated"].append(user)
	return result
