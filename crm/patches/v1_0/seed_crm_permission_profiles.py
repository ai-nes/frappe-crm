"""Seed CRM Permission Profile records from the existing role_policy catalog.

This is a read-only transcription of `crm.fcrm.role_policy` into the new
`CRM Permission Profile` doctype introduced for UI-driven role administration.
It changes no runtime behavior: `case_scope_for_roles()` and
`managed_docperm_rows()` remain the sole source Frappe consults until a later
phase switches their internals to read from these seeded records.

Legacy overlay roles are seeded with all-zero-flag `applicable_doctypes` rows
(one per doctype their overlay surfaces cover) because `_overlay_permission_set()`
(the function that would compute their "intended" CRUD) has no callers anywhere
in this codebase today -- legacy overlay roles currently receive zero DocPerm
grant on any canonical-matrix doctype (see `setup_crm_permissions.apply_managed_docperms`,
which deletes and never reinserts rows for them). The rows exist only to satisfy
the doctype's own `validate()` requirement of at least one row; every flag is 0
so this seeds no grant those roles do not actually have right now.

This patch computes canonical applicable_doctypes from `_hardcoded_managed_docperm_rows()`,
not the public `managed_docperm_rows()` -- the public function reads from this
same `CRM Permission Profile` table post-cutover, so using it here would make
this patch depend on the data it is trying to create.
"""

import frappe

from crm.fcrm.role_policy import (
	CANONICAL_PERMISSION_MATRIX,
	LEGACY_COMPATIBILITY_OVERLAYS,
	PROFILE_LABELS,
	SYSTEM_MANAGER_ROLE,
	_hardcoded_managed_docperm_rows,
)

# All seeded profiles adopt this per the explicit product decision (2026-09-03)
# to enforce PRD P0-3 ownership-gated delete for every role, canonical and
# legacy alike. This is a real behavior change for roles that previously had
# no ownership check on delete; see phase-05 of the role-policy rollout plan.
_DELETE_REQUIRES_OWNERSHIP = 1


def _canonical_row_scope(role):
	if role == SYSTEM_MANAGER_ROLE:
		return "all"
	profile = next(p for p, label in PROFILE_LABELS.items() if label == role)
	return CANONICAL_PERMISSION_MATRIX["admissions_case"]["row_scope"].get(profile, "deny")


def _is_matrix_derived_profile(role):
	"""True for the original `CANONICAL_PERMISSION_MATRIX`-backed profiles.

	PRD-phan-quyen-lead.md roles (`CTV Sale`, `Promoter`, `Lead Promoter`,
	`Lead Marketing`, `CEO`) are hand-transcribed by `seed_new_lead_role_profiles`
	instead -- they have no entry in the matrix, so deriving `applicable_doctypes`
	for them here would produce an empty row set and fail the doctype's own
	"at least one row" validation on every subsequent run of this patch.
	"""
	if role == SYSTEM_MANAGER_ROLE:
		return True
	profile = next((p for p, label in PROFILE_LABELS.items() if label == role), None)
	return profile in CANONICAL_PERMISSION_MATRIX["admissions_case"]["permissions"]


def _canonical_applicable_doctypes(role):
	rows = []
	for doctype, permissions in _hardcoded_managed_docperm_rows().items():
		for permission in permissions:
			if permission["role"] != role:
				continue
			rows.append(
				{
					"document_type": doctype,
					"read": permission.get("read", 0),
					"write": permission.get("write", 0),
					"create": permission.get("create", 0),
					"delete": permission.get("delete", 0),
					"export": permission.get("export", 0),
				}
			)
	return rows


def _overlay_row_scope(template):
	scope = template["row_scope"]
	return "all" if scope == "all_cases" else scope


# Maps each overlay template's permission key to the matrix surface whose
# `doctypes` tuple it covers, so a seeded profile lists every doctype the
# legacy role is conceptually scoped to -- even though every flag is 0.
_OVERLAY_KEY_TO_SURFACE = {
	"case_permissions": "admissions_case",
	"reference_permissions": "reference",
	"acquisition_permissions": "acquisition",
	"governed_acquisition_permissions": "governed_acquisition",
	"governed_admissions_permissions": "governed_admissions",
	"attribution_evidence_permissions": "attribution_evidence",
	"control_permissions": "control_plane",
}


def _overlay_applicable_doctypes(template):
	doctypes = []
	for key in template:
		surface = _OVERLAY_KEY_TO_SURFACE.get(key)
		if surface:
			doctypes.extend(CANONICAL_PERMISSION_MATRIX[surface]["doctypes"])
	# Legacy overlay roles receive zero DocPerm grant on every canonical-matrix
	# doctype today (see module docstring); flags stay 0 to match that exactly.
	return [
		{"document_type": doctype, "read": 0, "write": 0, "create": 0, "delete": 0, "export": 0}
		for doctype in dict.fromkeys(doctypes)
	]


def _upsert_profile(role, row_scope, applicable_doctypes):
	if not frappe.db.exists("Role", role):
		return
	name = frappe.db.get_value("CRM Permission Profile", {"role": role}, "name")
	if name:
		doc = frappe.get_doc("CRM Permission Profile", name)
		doc.set("applicable_doctypes", [])
	else:
		doc = frappe.new_doc("CRM Permission Profile")
		doc.role = role
	doc.row_scope = row_scope
	doc.delete_requires_ownership = _DELETE_REQUIRES_OWNERSHIP
	doc.is_system_managed = 1
	for row in applicable_doctypes:
		doc.append("applicable_doctypes", row)
	doc.save(ignore_permissions=True)


def execute():
	if not frappe.db.exists("DocType", "CRM Permission Profile"):
		return

	for role in (SYSTEM_MANAGER_ROLE, *PROFILE_LABELS.values()):
		if not _is_matrix_derived_profile(role):
			continue
		_upsert_profile(role, _canonical_row_scope(role), _canonical_applicable_doctypes(role))

	for template in LEGACY_COMPATIBILITY_OVERLAYS.values():
		row_scope = _overlay_row_scope(template)
		applicable_doctypes = _overlay_applicable_doctypes(template)
		for role in template["roles"]:
			_upsert_profile(role, row_scope, applicable_doctypes)
