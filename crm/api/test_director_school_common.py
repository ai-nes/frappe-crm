"""Tests for the shared Director projection security and resolver contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import director_school_common as common


class TestDirectorSchoolCommon(FrappeTestCase):
	def test_admission_director_is_allowed_by_canonical_role_state(self):
		with patch.object(common.frappe, "session", SimpleNamespace(user="director@example.com")), patch.object(
			common.frappe.db, "get_value", return_value=1
		), patch.object(common.frappe, "get_roles", return_value=["Admissions Director"]), patch.object(
			common, "classify_role_set", return_value="canonical_profile"
		), patch.object(common, "resolve_crm_profile", return_value="admissions_director"):
			access = common.require_director_access()

		self.assertEqual(access["roleState"], "canonical_profile")

	def test_mixed_role_set_is_forbidden_even_if_one_role_is_allowed(self):
		with patch.object(common.frappe, "session", SimpleNamespace(user="mixed@example.com")), patch.object(
			common.frappe.db, "get_value", return_value=1
		), patch.object(common.frappe, "get_roles", return_value=["Admissions Director", "Marketing"]), patch.object(
			common, "classify_role_set", return_value="mixed_or_unmapped"
		), patch.object(common, "resolve_crm_profile", return_value=None):
			with self.assertRaises(frappe.PermissionError):
				common.require_director_access()

	def test_system_manager_and_administrator_are_explicitly_allowed(self):
		with patch.object(common.frappe, "session", SimpleNamespace(user="manager@example.com")), patch.object(
			common.frappe.db, "get_value", return_value=1
		), patch.object(common.frappe, "get_roles", return_value=["System Manager"]), patch.object(
			common, "classify_role_set", return_value="system_manager"
		), patch.object(common, "resolve_crm_profile", return_value=None):
			self.assertEqual(common.require_director_access()["roleState"], "system_manager")

		with patch.object(common.frappe, "session", SimpleNamespace(user="Administrator")), patch.object(
			common.frappe, "get_roles", return_value=["System Manager"]
		), patch.object(common, "classify_role_set", return_value="platform_superuser"):
			self.assertEqual(common.require_director_access()["roleState"], "platform_superuser")

	def test_guest_is_unauthenticated(self):
		with patch.object(common.frappe, "session", SimpleNamespace(user="Guest")):
			with self.assertRaises(frappe.AuthenticationError):
				common.require_director_access()

	def test_query_parsers_are_strict(self):
		self.assertEqual(common.parse_admission_year("2026"), "2026")
		self.assertEqual(common.parse_boolean("false", field="includeSchools", default=True), False)
		self.assertEqual(common.parse_limit("6", field="schoolLimit", minimum=1, maximum=20, default=1), 6)
		with self.assertRaises(frappe.ValidationError):
			common.parse_admission_year("26")
		with self.assertRaises(frappe.ValidationError):
			common.parse_boolean("yes", field="includeSchools", default=True)
		with self.assertRaises(frappe.ValidationError):
			common.parse_boolean("1", field="includeSchools", default=True)
		with self.assertRaises(frappe.ValidationError):
			common.parse_limit("21", field="schoolLimit", minimum=1, maximum=20, default=1)

	def test_resolver_uses_canonical_ward_key(self):
		province = [{"name": "province-1"}]
		school = [{
			"name": "school-1", "school_name": "THPT Test", "school_code": "062", "province": "province-1",
			"ward": "ward-1", "school_area": None, "school_tier": None, "boarding_type": None,
			"latitude": None, "longitude": None, "address": None, "is_key_account": 0,
		}]
		ward = [{"name": "ward-1", "ward_code": "00123"}]
		with patch.object(common.frappe, "get_list", side_effect=[province, ward, school]):
			resolved = common.resolve_school_id("01-00123-062")

		self.assertEqual(resolved["ward"], "ward-1")

	def test_legacy_collision_fails_closed_without_name_fallback(self):
		province = [{"name": "province-1"}]
		collision = [{"name": "school-1"}, {"name": "school-2"}]
		with patch.object(common.frappe, "get_list", side_effect=[province, collision]):
			with self.assertRaises(frappe.DoesNotExistError):
				common.resolve_school_id("01-01-062")

	def test_availability_preserves_zero(self):
		self.assertEqual(common.fact(0), {"value": 0, "availability": "available"})
		self.assertEqual(common.fact(None), {"value": None, "availability": "unavailable"})

	def test_resolver_returns_verified_canonical_identity(self):
		province = [{"name": "province-1"}]
		ward = [{"name": "ward-1", "ward_code": "00123"}]
		school = [{"name": "school-1", "school_code": "062", "province": "province-1", "ward": "ward-1"}]
		with patch.object(common.frappe, "get_list", side_effect=[province, ward, school]):
			resolved = common.resolve_school_id("01-00123-062")

		self.assertEqual(resolved["canonical_id"], "01-00123-062")
		self.assertEqual(resolved["province_code"], "01")
		self.assertEqual(resolved["ward_code"], "00123")

	def test_system_manager_mixed_with_business_role_is_forbidden(self):
		with (
			patch.object(common.frappe, "session", SimpleNamespace(user="mixed-manager@example.test")),
			patch.object(common.frappe.db, "get_value", return_value=1),
			patch.object(common.frappe, "get_roles", return_value=["System Manager", "Admissions Director"]),
			self.assertRaises(frappe.PermissionError),
		):
			common.require_director_access()
