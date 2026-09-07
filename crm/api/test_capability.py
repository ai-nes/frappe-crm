from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.capability import (
	_can_manage_ai_exposure,
	_project_ai_fields,
	_safe_student_filters,
	validate_ai_exposed_change,
)


class _FakeDoc:
	def __init__(self, *, is_new=False, current=False, previous=False):
		self._is_new = is_new
		self._current = current
		self._previous = previous

	def is_new(self):
		return self._is_new

	def get(self, fieldname):
		assert fieldname == "custom_ai_exposed"
		return self._current

	def get_doc_before_save(self):
		return {"custom_ai_exposed": self._previous}


class TestAiExposureAuthority(FrappeTestCase):
	def test_student_projection_includes_contact_pii_when_readable(self):
		"""PII is gated only by real permlevel access (`fields` already reflects
		that), not by a second role-identity check -- the same fields the role
		already sees in the CRM desk UI."""
		fields = ["name", "full_name", "phone", "email", "date_of_birth", "id_number", "latest_score"]
		self.assertEqual(
			_project_ai_fields("CRM Student", fields),
			["email", "full_name", "latest_score", "name", "phone"],
		)

	def test_student_projection_excludes_fields_outside_the_operational_pii_ceiling(self):
		fields = ["name", "latest_score", "date_of_birth", "id_number"]
		self.assertEqual(
			_project_ai_fields("CRM Student", fields),
			["latest_score", "name"],
		)

	def test_student_dto_filters_cannot_target_hidden_pii(self):
		allowed = {"name", "latest_score"}
		self.assertEqual(
			_safe_student_filters([["latest_score", "=", 0.8]], allowed), [["latest_score", "=", 0.8]]
		)
		with self.assertRaises(frappe.PermissionError):
			_safe_student_filters([["phone", "=", "0900000000"]], allowed)

	def test_only_system_manager_has_exposure_authority(self):
		self.assertTrue(_can_manage_ai_exposure({"System Manager"}))
		self.assertTrue(_can_manage_ai_exposure({"System Manager", "AI Capability Admin"}))
		self.assertFalse(_can_manage_ai_exposure({"Administrator"}))
		self.assertFalse(_can_manage_ai_exposure({"AI Capability Admin"}))
		self.assertFalse(_can_manage_ai_exposure({"Sale"}))

	def test_legacy_admin_and_administrator_cannot_change_exposure(self):
		for roles in ({"AI Capability Admin"}, {"Administrator"}, {"Sale"}):
			with self.subTest(roles=roles), patch("crm.api.capability.frappe.get_roles", return_value=roles):
				with self.assertRaises(frappe.PermissionError):
					validate_ai_exposed_change(_FakeDoc(current=True, previous=False))

	def test_system_manager_can_change_exposure(self):
		with patch("crm.api.capability.frappe.get_roles", return_value={"System Manager"}):
			validate_ai_exposed_change(_FakeDoc(current=True, previous=False))


class TestCanonicalRoleManifestIdentities(FrappeTestCase):
	"""Bench/Docker probe using real User role assignments, not mocked roles."""

	def tearDown(self):
		frappe.set_user("Administrator")
		for email in getattr(self, "_created_users", []):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True)

	def _user(self, role: str) -> str:
		if not hasattr(self, "_created_users"):
			self._created_users = []
		email = f"_test_manifest_{frappe.scrub(role)}@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Manifest",
				"user_type": "System User",
				"send_welcome_email": 0,
				"roles": [{"role": role}],
			}
		).insert(ignore_permissions=True)
		self._created_users.append(user.name)
		return user.name

	def test_real_canonical_identities_publish_their_own_manifest_role(self):
		from crm.api.capability import get_capability_manifest

		for role in ("Sale", "Lead Sale", "Marketing", "Admissions Director"):
			with self.subTest(role=role):
				frappe.set_user(self._user(role))
				manifest = get_capability_manifest()
				self.assertIn(role, manifest["roles"])
				self.assertEqual(manifest["crm_role"], role)
				self.assertEqual(manifest["role_matrix_epoch"], "crm-roles-v1")

	def test_system_manager_real_identity_has_no_copilot_manifest(self):
		from crm.api.capability import get_capability_manifest

		frappe.set_user(self._user("System Manager"))
		with self.assertRaises(frappe.PermissionError):
			get_capability_manifest()

	def test_capability_revision_is_stable_for_an_unchanged_role_set(self):
		from crm.api.capability import get_capability_revision

		frappe.set_user(self._user("Sale"))
		revision = get_capability_revision()
		self.assertIn("Sale", revision["roles"])
		self.assertEqual(get_capability_revision()["revision"], revision["revision"])

	def test_capability_revision_changes_when_a_granted_role_is_edited(self):
		from crm.api.capability import get_capability_revision

		frappe.set_user(self._user("Sale"))
		before = get_capability_revision()
		role = frappe.get_doc("Role", "Sale")
		original_home_page = role.home_page
		try:
			role.home_page = f"{original_home_page or '/app'}?capability_revision_probe=1"
			role.save(ignore_permissions=True)
			after = get_capability_revision()
			self.assertNotEqual(before["revision"], after["revision"])
		finally:
			role.home_page = original_home_page
			role.save(ignore_permissions=True)

	def test_capability_revision_denies_system_manager(self):
		from crm.api.capability import get_capability_revision

		frappe.set_user(self._user("System Manager"))
		with self.assertRaises(frappe.PermissionError):
			get_capability_revision()
