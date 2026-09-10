import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.role_policy import (
	CANONICAL_PERMISSION_MATRIX,
	LEGACY_COMPATIBILITY_OVERLAYS,
	LEGACY_OVERLAY_ROLES,
	PERMISSION_PROFILE_KILL_SWITCH_CONFIG_KEY,
	PROFILE_LABELS,
	SYSTEM_MANAGER_ROLE,
	_hardcoded_case_scope_for_roles,
	_hardcoded_managed_docperm_rows,
	case_scope_for_roles,
	delete_requires_ownership_for_roles,
	managed_docperm_rows,
)
from crm.patches.v1_0.seed_crm_permission_profiles import _is_matrix_derived_profile
from crm.patches.v1_0.seed_crm_permission_profiles import execute as seed_permission_profiles
from crm.patches.v1_0.seed_new_lead_role_profiles import execute as seed_new_lead_role_profiles

_ADMISSIONS_CASE_DOCTYPES = CANONICAL_PERMISSION_MATRIX["admissions_case"]["doctypes"]


class TestRolePolicyDbCutover(FrappeTestCase):
	"""Phase 4: `case_scope_for_roles`/`managed_docperm_rows` now read from the
	seeded `CRM Permission Profile` table by default. These tests prove that
	read is identical to the retained hardcoded-matrix fallback (which only
	runs behind the `crm_permission_profile_use_hardcoded_matrix` kill-switch),
	and that the kill-switch itself actually restores the old behavior.
	"""

	def setUp(self):
		seed_permission_profiles()
		seed_new_lead_role_profiles()
		frappe.conf.pop(PERMISSION_PROFILE_KILL_SWITCH_CONFIG_KEY, None)

	def tearDown(self):
		frappe.conf.pop(PERMISSION_PROFILE_KILL_SWITCH_CONFIG_KEY, None)
		frappe.db.rollback()

	def test_module_import_does_not_touch_the_database(self):
		import ast
		import inspect

		import crm.fcrm.role_policy as role_policy_module

		tree = ast.parse(inspect.getsource(role_policy_module))
		for node in tree.body:
			if isinstance(node, ast.Import) and any(alias.name == "frappe" for alias in node.names):
				self.fail("role_policy.py must not import frappe at module level")
			if isinstance(node, ast.ImportFrom) and node.module == "frappe":
				self.fail("role_policy.py must not import from frappe at module level")

	def test_managed_docperm_rows_matches_hardcoded_fallback_for_matrix_derived_roles(self):
		"""The kill-switch fallback only knows the original matrix-derived
		roles -- the PRD-phan-quyen-lead.md roles (`CTV Sale`, `Promoter`,
		`Lead Promoter`, `Lead Marketing`, `CEO`) are hand-transcribed and were
		deliberately never added to `CANONICAL_PERMISSION_MATRIX` (see
		`_is_matrix_derived_profile`), so the fallback intentionally grants
		them nothing. Restrict the row-for-row comparison to the roles the
		fallback actually models.
		"""
		live_rows = managed_docperm_rows()
		hardcoded_rows = _hardcoded_managed_docperm_rows()
		for doctype, rows in hardcoded_rows.items():
			with self.subTest(doctype=doctype):
				live_by_role = {row["role"]: row for row in live_rows.get(doctype, [])}
				for row in rows:
					self.assertEqual(live_by_role.get(row["role"]), row)

	def test_managed_docperm_rows_grants_new_prd_roles_that_the_hardcoded_fallback_denies(self):
		live_rows = managed_docperm_rows()
		hardcoded_roles = {row["role"] for rows in _hardcoded_managed_docperm_rows().values() for row in rows}
		new_roles = {role for role in PROFILE_LABELS.values() if not _is_matrix_derived_profile(role)}
		for doctype in _ADMISSIONS_CASE_DOCTYPES:
			live_roles = {row["role"] for row in live_rows.get(doctype, [])}
			for role in new_roles:
				with self.subTest(doctype=doctype, role=role):
					self.assertIn(role, live_roles)
					self.assertNotIn(role, hardcoded_roles)

	def test_row_scope_matches_hardcoded_fallback_for_every_canonical_profile(self):
		for role in (SYSTEM_MANAGER_ROLE, *PROFILE_LABELS.values()):
			if not _is_matrix_derived_profile(role):
				# Hand-transcribed PRD roles have no matrix entry; the
				# kill-switch fallback safely degrades them to "deny" rather
				# than modeling their real scope. See
				# `_is_matrix_derived_profile` for why.
				continue
			for doctype in _ADMISSIONS_CASE_DOCTYPES:
				with self.subTest(role=role, doctype=doctype):
					self.assertEqual(
						case_scope_for_roles({role}, doctype),
						_hardcoded_case_scope_for_roles({role}, doctype),
					)

	def test_new_prd_roles_fall_back_to_deny_under_the_kill_switch(self):
		for role in PROFILE_LABELS.values():
			if _is_matrix_derived_profile(role):
				continue
			for doctype in _ADMISSIONS_CASE_DOCTYPES:
				with self.subTest(role=role, doctype=doctype):
					self.assertEqual(_hardcoded_case_scope_for_roles({role}, doctype), "deny")

	def test_row_scope_matches_hardcoded_fallback_for_every_legacy_overlay_role(self):
		for role in LEGACY_OVERLAY_ROLES:
			if not frappe.db.exists("Role", role):
				continue
			for doctype in (*_ADMISSIONS_CASE_DOCTYPES, "CRM Student"):
				with self.subTest(role=role, doctype=doctype):
					self.assertEqual(
						case_scope_for_roles({role}, doctype),
						_hardcoded_case_scope_for_roles({role}, doctype),
					)

	def test_promoter_pr_campus_assigned_contact_is_doctype_conditional(self):
		role = "Promoter-PR"
		if not frappe.db.exists("Role", role):
			self.skipTest("Promoter-PR role not present on this site")
		self.assertEqual(case_scope_for_roles({role}, "CRM Student"), "campus_assigned_contact")
		self.assertEqual(case_scope_for_roles({role}, "CRM Lead"), "deny")

	def test_all_cases_overlay_normalizes_to_all(self):
		for overlay, template in LEGACY_COMPATIBILITY_OVERLAYS.items():
			if template["row_scope"] != "all_cases":
				continue
			for role in template["roles"]:
				if not frappe.db.exists("Role", role):
					continue
				with self.subTest(overlay=overlay, role=role):
					self.assertEqual(case_scope_for_roles({role}, "CRM Lead"), "all")

	def test_unknown_role_denies(self):
		role = "_Test Role Policy Unknown Role"
		self.assertEqual(case_scope_for_roles({role}, "CRM Lead"), "deny")

	def test_administrator_is_all_without_touching_the_database(self):
		self.assertEqual(case_scope_for_roles(set(), "CRM Lead", administrator=True), "all")

	def test_editing_a_profile_is_visible_on_the_next_read(self):
		name = frappe.db.get_value("CRM Permission Profile", {"role": "Sale"}, "name")
		doc = frappe.get_doc("CRM Permission Profile", name)
		self.assertEqual(case_scope_for_roles({"Sale"}, "CRM Lead"), "assigned")

		doc.row_scope = "all"
		doc.save(ignore_permissions=True)

		self.assertEqual(case_scope_for_roles({"Sale"}, "CRM Lead"), "all")

	def test_missing_profile_for_a_resolvable_identity_falls_back_to_deny_and_logs(self):
		name = frappe.db.get_value("CRM Permission Profile", {"role": "Marketing"}, "name")
		frappe.delete_doc("CRM Permission Profile", name, ignore_permissions=True, delete_permanently=True)

		error_count_before = frappe.db.count("Error Log")
		self.assertEqual(case_scope_for_roles({"Marketing"}, "CRM Lead"), "deny")
		self.assertGreater(frappe.db.count("Error Log"), error_count_before)

	def test_delete_requires_ownership_is_on_for_every_seeded_profile(self):
		for role in (SYSTEM_MANAGER_ROLE, *PROFILE_LABELS.values()):
			with self.subTest(role=role):
				self.assertTrue(delete_requires_ownership_for_roles({role}))

	def test_delete_requires_ownership_administrator_bypasses(self):
		self.assertFalse(delete_requires_ownership_for_roles(set(), administrator=True))

	def test_delete_requires_ownership_unknown_role_is_false_since_scope_already_denies(self):
		self.assertFalse(delete_requires_ownership_for_roles({"_Test Role Policy Unknown Role"}))

	def test_delete_requires_ownership_kill_switch_restores_no_ownership_gate(self):
		frappe.conf[PERMISSION_PROFILE_KILL_SWITCH_CONFIG_KEY] = 1
		try:
			self.assertFalse(delete_requires_ownership_for_roles({"Sale"}))
		finally:
			frappe.conf.pop(PERMISSION_PROFILE_KILL_SWITCH_CONFIG_KEY, None)

	def test_kill_switch_forces_hardcoded_matrix(self):
		name = frappe.db.get_value("CRM Permission Profile", {"role": "Sale"}, "name")
		doc = frappe.get_doc("CRM Permission Profile", name)
		doc.row_scope = "all"
		doc.save(ignore_permissions=True)

		# Without the kill-switch, the DB edit takes effect immediately.
		self.assertEqual(case_scope_for_roles({"Sale"}, "CRM Lead"), "all")

		frappe.conf[PERMISSION_PROFILE_KILL_SWITCH_CONFIG_KEY] = 1
		try:
			# With it set, the hardcoded matrix wins even though the DB record
			# now disagrees -- proving the kill-switch is a real bypass, not
			# just a no-op flag.
			self.assertEqual(case_scope_for_roles({"Sale"}, "CRM Lead"), "assigned")
			self.assertEqual(managed_docperm_rows(), _hardcoded_managed_docperm_rows())
		finally:
			frappe.conf.pop(PERMISSION_PROFILE_KILL_SWITCH_CONFIG_KEY, None)
