import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.role_policy import (
	CANONICAL_PERMISSION_MATRIX,
	LEGACY_COMPATIBILITY_OVERLAYS,
	LEGACY_OVERLAY_ROLES,
	PROFILE_LABELS,
	SYSTEM_MANAGER_ROLE,
	managed_docperm_rows,
)
from crm.patches.v1_0.seed_crm_permission_profiles import _is_matrix_derived_profile, execute


class TestSeedCrmPermissionProfiles(FrappeTestCase):
	def setUp(self):
		execute()

	def tearDown(self):
		frappe.db.rollback()

	def _profile(self, role):
		name = frappe.db.get_value("CRM Permission Profile", {"role": role}, "name")
		self.assertTrue(name, f"expected a seeded CRM Permission Profile for role {role!r}")
		return frappe.get_doc("CRM Permission Profile", name)

	def test_canonical_profiles_match_managed_docperm_rows(self):
		docperm_rows = managed_docperm_rows()
		for role in (SYSTEM_MANAGER_ROLE, *PROFILE_LABELS.values()):
			if not _is_matrix_derived_profile(role):
				# PRD-phan-quyen-lead.md roles are hand-transcribed by
				# `seed_new_lead_role_profiles`, not this patch -- see
				# `test_seed_new_lead_role_profiles.py`.
				continue
			profile = self._profile(role)
			self.assertEqual(profile.is_system_managed, 1)
			self.assertEqual(profile.delete_requires_ownership, 1)

			expected = {}
			for doctype, permissions in docperm_rows.items():
				for permission in permissions:
					if permission["role"] == role:
						expected[doctype] = permission

			seeded = {row.document_type: row for row in profile.applicable_doctypes}
			self.assertEqual(set(seeded), set(expected))
			for doctype, permission in expected.items():
				row = seeded[doctype]
				self.assertEqual(bool(row.read), bool(permission.get("read")))
				self.assertEqual(bool(row.write), bool(permission.get("write")))
				self.assertEqual(bool(row.create), bool(permission.get("create")))
				self.assertEqual(bool(row.delete), bool(permission.get("delete")))
				self.assertEqual(bool(row.export), bool(permission.get("export")))

	def test_canonical_row_scope_matches_admissions_case_matrix(self):
		self.assertEqual(self._profile(SYSTEM_MANAGER_ROLE).row_scope, "all")
		self.assertEqual(self._profile("Sale").row_scope, "assigned")
		self.assertEqual(self._profile("Lead Sale").row_scope, "team_and_team_pool")
		self.assertEqual(self._profile("Admissions Director").row_scope, "all")
		self.assertEqual(
			self._profile("Marketing").row_scope,
			CANONICAL_PERMISSION_MATRIX["admissions_case"]["row_scope"]["marketing"],
		)

	def test_legacy_overlay_roles_have_zero_docperm_grant(self):
		for role in LEGACY_OVERLAY_ROLES:
			if not frappe.db.exists("Role", role):
				continue
			profile = self._profile(role)
			self.assertGreater(len(profile.applicable_doctypes), 0)
			for row in profile.applicable_doctypes:
				self.assertFalse(row.read)
				self.assertFalse(row.write)
				self.assertFalse(row.create)
				self.assertFalse(row.delete)
				self.assertFalse(row.export)

	def test_legacy_overlay_row_scope_matches_policy_with_all_cases_normalized(self):
		for template in LEGACY_COMPATIBILITY_OVERLAYS.values():
			expected = "all" if template["row_scope"] == "all_cases" else template["row_scope"]
			for role in template["roles"]:
				if not frappe.db.exists("Role", role):
					continue
				self.assertEqual(self._profile(role).row_scope, expected)

	def test_seed_is_idempotent(self):
		execute()
		execute()
		profile = self._profile("Sale")
		doctypes = [row.document_type for row in profile.applicable_doctypes]
		self.assertEqual(len(doctypes), len(set(doctypes)))
