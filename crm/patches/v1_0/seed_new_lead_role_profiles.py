"""Seed the PRD-phan-quyen-lead.md roles that `CANONICAL_PERMISSION_MATRIX`
does not cover: CTV Sale, Promoter (PR nhân viên), Lead Promoter (Trưởng
phòng PR), Lead Marketing (Trưởng phòng Marketing), CEO.

Unlike `seed_crm_permission_profiles`, these `CRM Permission Profile` rows are
hand-transcribed directly from the PRD's P0-1 CRUD matrix rather than derived
from `CANONICAL_PERMISSION_MATRIX` -- these roles have no entry there. This
patch also re-runs `seed_crm_permission_profiles.execute()` and
`apply_managed_docperms()` so the same deploy picks up the PRD's P0-1 changes
to the already-active Lead Sale (adds conditional delete) and Marketing
(adds campus-scoped read) profiles.

Field-level restriction of CTV Sale to "note/status" fields (PRD P0-1
acceptance criteria, Open Question #2) is not implemented here -- the PRD
itself leaves the exact field list unresolved, so CTV Sale is seeded with an
unrestricted write flag on CRM Lead/CRM Contact as an interim measure.
"""

import frappe

from crm.fcrm.role_policy import CANONICAL_PERMISSION_MATRIX, PROFILE_LABELS
from crm.patches.v1_0.seed_crm_permission_profiles import _upsert_profile
from crm.patches.v1_0.seed_crm_permission_profiles import execute as seed_matrix_derived_profiles
from crm.patches.v1_0.setup_crm_permissions import apply_managed_docperms
from crm.patches.v1_0.setup_crm_roles import create_roles

_ADMISSIONS_CASE_DOCTYPES = CANONICAL_PERMISSION_MATRIX["admissions_case"]["doctypes"]

# These are the read-only sources consumed by the two Director projections
# exposed to CTV Sale. Keep this list explicit: the CTV profile must not inherit
# the broader reference-data permissions of the canonical Sale profile.
CTV_SALE_DIRECTOR_READ_DOCTYPES = (
	"CRM Admission Method",
	"CRM Admission Year",
	"CRM Admission Offering",
	"CRM Admission Profile Template",
	"CRM Aspiration",
	"CRM Document Type",
	"CRM School Area",
	"CRM Admission Application",
	"CRM Student Admission Profile",
	"CRM Student Document",
	"CRM High School",
	"CRM Province",
	"CRM Ward",
	"CRM High School Annual Snapshot",
	"CRM Recommendation",
	"CRM Campaign",
	"Call Log",
)

# PRD-phan-quyen-lead.md P0-1 CRUD matrix, hand-transcribed. Every role here
# gets `delete_requires_ownership=1` regardless of whether it has a delete
# flag at all, matching every other seeded profile (see
# `seed_crm_permission_profiles._DELETE_REQUIRES_OWNERSHIP`).
_NEW_ROLE_PERMISSIONS = {
	# CTV Sale: read + limited write (note/status only -- unresolved field
	# list, see module docstring), no create, no delete.
	"ctv_sale": {"row_scope": "assigned", "read": 1, "write": 1, "create": 0, "delete": 0},
	# Promoter (PR nhân viên): create + read only, cannot edit/delete once
	# handed off to Sale.
	"pr": {"row_scope": "campus_assigned", "read": 1, "write": 0, "create": 1, "delete": 0},
	# Lead Promoter (Trưởng phòng PR): full CRUD within campus; delete gated
	# by delete_requires_ownership (PRD P0-3).
	"pr_manager": {"row_scope": "campus_assigned", "read": 1, "write": 1, "create": 1, "delete": 1},
	# Lead Marketing (Trưởng phòng Marketing): read-only, same as Marketing.
	"lead_marketing": {"row_scope": "campus_assigned", "read": 1, "write": 0, "create": 0, "delete": 0},
	# CEO: full CRUD across all campuses; delete still gated by ownership,
	# no exception even for CEO (PRD P0-3, explicit).
	"ceo": {"row_scope": "all", "read": 1, "write": 1, "create": 1, "delete": 1},
}

_NEW_ROLE_NAMES = tuple(PROFILE_LABELS[profile] for profile in _NEW_ROLE_PERMISSIONS if PROFILE_LABELS[profile] != "Promoter")


def _applicable_doctypes(flags, extra_read_doctypes=()):
	rows = [
		{
			"document_type": doctype,
			"read": flags["read"],
			"write": flags["write"],
			"create": flags["create"],
			"delete": flags["delete"],
			"export": 0,
		}
		for doctype in _ADMISSIONS_CASE_DOCTYPES
	]
	rows.extend(
		{
			"document_type": doctype,
			"read": 1,
			"write": 0,
			"create": 0,
			"delete": 0,
			"export": 0,
		}
		for doctype in extra_read_doctypes
	)
	return rows


def execute():
	if not frappe.db.exists("DocType", "CRM Permission Profile"):
		return

	# "Promoter" already exists as a Role (reused per explicit product
	# decision, 2026-09-04); only the net-new role names need creating.
	create_roles(_NEW_ROLE_NAMES)

	for profile, flags in _NEW_ROLE_PERMISSIONS.items():
		role = PROFILE_LABELS[profile]
		extra_read_doctypes = CTV_SALE_DIRECTOR_READ_DOCTYPES if profile == "ctv_sale" else ()
		_upsert_profile(
			role,
			flags["row_scope"],
			_applicable_doctypes(flags, extra_read_doctypes),
		)

	# Picks up this deploy's P0-1 changes to the already-active Lead Sale
	# (conditional delete) and Marketing (campus-scoped read) profiles.
	seed_matrix_derived_profiles()
	apply_managed_docperms()
