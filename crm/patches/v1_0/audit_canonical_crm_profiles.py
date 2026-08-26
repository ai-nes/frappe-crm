"""Read-only Phase 2 profile audit for controlled post-deploy evidence."""

import frappe

from crm.fcrm.role_policy import POLICY_VERSION, classify_role_set


def execute():
	"""Return deterministic classification evidence; intentionally performs no writes."""
	groups = {state: [] for state in ("canonical", "alias", "unmapped", "mixed_profile", "missing_staff")}
	for user in frappe.get_all("User", filters={"enabled": 1}, fields=["name"]):
		name = user.name
		if name == "Guest":
			continue
		if name == "Administrator":
			state = "canonical"
		else:
			state = classify_role_set(frappe.get_roles(name))
			if state in {"canonical_profile", "compatibility_overlay"} and not frappe.db.exists(
				"CRM Staff", {"user": name}
			):
				state = "missing_staff"
			else:
				state = {
					"canonical_profile": "canonical",
					"compatibility_overlay": "alias",
					"system_manager": "canonical",
					"mixed_or_unmapped": "mixed_profile",
					"legacy_migration_required": "unmapped",
					"unmapped": "unmapped",
				}.get(state, "unmapped")
		groups[state].append(name)

	return {
		"policy_version": POLICY_VERSION,
		"generated_at": frappe.utils.now_datetime().isoformat(),
		"counts": {state: len(names) for state, names in groups.items()},
		"users": {state: sorted(names) for state, names in groups.items()},
	}
