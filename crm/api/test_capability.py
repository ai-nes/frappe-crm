from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.capability import (
	_can_manage_ai_exposure,
	_has_self_scoped_student_pii,
	_project_ai_fields,
	_safe_student_filters,
	_student_ai_exposure_enabled,
	get_ai_student,
	get_exposed_doctypes,
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
	def test_student_projection_limits_pii_to_sales(self):
		fields = ["name", "student_name", "phone", "email", "date_of_birth", "id_number", "latest_score"]
		self.assertEqual(
			_project_ai_fields("CRM Student", fields, {"Sale"}),
			["email", "latest_score", "name", "phone", "student_name"],
		)
		self.assertEqual(
			_project_ai_fields("CRM Student", fields, {"Marketing"}),
			["latest_score", "name"],
		)
		self.assertEqual(
			_project_ai_fields("CRM Student", fields, {"Lead Sales"}),
			["latest_score", "name"],
		)
		self.assertFalse(_has_self_scoped_student_pii({"Sale", "Lead Sales"}))
		self.assertFalse(_has_self_scoped_student_pii({"Sale", "Marketing"}))
		self.assertFalse(_has_self_scoped_student_pii({"Sale", "Admissions Director"}))

	def test_student_dto_filters_cannot_target_hidden_pii(self):
		allowed = {"name", "latest_score"}
		self.assertEqual(_safe_student_filters([["latest_score", "=", 0.8]], allowed), [["latest_score", "=", 0.8]])
		with self.assertRaises(frappe.PermissionError):
			_safe_student_filters([["phone", "=", "0900000000"]], allowed)

	def test_student_dto_is_disabled_without_explicit_staging_gate(self):
		with patch("crm.api.capability._student_ai_exposure_enabled", return_value=False):
			with self.assertRaises(frappe.PermissionError):
				get_ai_student("STU-FOREIGN")

	def test_student_staging_gate_requires_environment_and_exposure_flag(self):
		with (
			patch("crm.api.capability.frappe.conf", {"ai_student_exposure_environment": "staging"}),
			patch("crm.api.capability.frappe.db.get_value", return_value=True),
		):
			self.assertTrue(_student_ai_exposure_enabled())
		with (
			patch("crm.api.capability.frappe.conf", {"ai_student_exposure_environment": "production"}),
			patch("crm.api.capability.frappe.db.get_value", return_value=True),
		):
			self.assertFalse(_student_ai_exposure_enabled())

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

	def test_schema_roster_requires_system_manager_only(self):
		with (
			patch("crm.api.capability.frappe.get_roles", return_value={"System Manager"}),
			patch("crm.api.capability.frappe.get_all", return_value=[]),
		):
			self.assertEqual(get_exposed_doctypes(), {"doctypes": []})

	def test_schema_roster_denies_administrator_without_system_manager(self):
		with patch("crm.api.capability.frappe.get_roles", return_value={"Administrator"}):
			with self.assertRaises(frappe.PermissionError):
				get_exposed_doctypes()


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
		user = frappe.get_doc({
			"doctype": "User", "email": email, "first_name": "Manifest",
			"user_type": "System User", "send_welcome_email": 0,
			"roles": [{"role": role}],
		}).insert(ignore_permissions=True)
		self._created_users.append(user.name)
		return user.name

	def test_real_canonical_identities_publish_their_own_manifest_role(self):
		from crm.api.capability import get_capability_manifest

		for role in ("Sale", "Lead Sales", "Marketing", "Admissions Director"):
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
