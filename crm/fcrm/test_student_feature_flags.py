from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.api.session import _crm_feature_flags
from crm.fcrm.student_feature_flags import (
	assignment_mode,
	automatic_assignment_on_create_enabled,
	director_analytics_read_enabled,
	enabled,
	role_workspace_read_enabled,
)


class TestStudentFeatureFlags(FrappeTestCase):
	def test_role_workspace_reader_is_disabled_by_default(self):
		with patch("crm.fcrm.student_feature_flags.frappe.conf", {}):
			self.assertFalse(role_workspace_read_enabled())

	def test_assignment_defaults_to_manual_batch(self):
		with (
			patch("crm.fcrm.student_feature_flags.frappe.conf", {}),
			patch("crm.fcrm.student_feature_flags.frappe.db.exists", return_value=False),
		):
			self.assertEqual(assignment_mode(), "manual_batch")

	def test_automatic_assignment_requires_explicit_compatibility_mode(self):
		with (
			patch("crm.fcrm.student_feature_flags.enabled", return_value=True),
			patch("crm.fcrm.student_feature_flags.assignment_mode", return_value="manual_batch"),
		):
			self.assertFalse(automatic_assignment_on_create_enabled())
		with (
			patch("crm.fcrm.student_feature_flags.enabled", return_value=True),
			patch("crm.fcrm.student_feature_flags.assignment_mode", return_value="automatic_on_create"),
		):
			self.assertTrue(automatic_assignment_on_create_enabled())

	def test_role_workspace_reader_uses_only_its_server_owned_key(self):
		with patch("crm.fcrm.student_feature_flags.frappe.conf", {"crm_student_role_workspace_read_enabled": 1}):
			self.assertTrue(role_workspace_read_enabled())
		with patch("crm.fcrm.student_feature_flags.frappe.conf", {"crm_student_role_workspace_read_enabled": "false"}):
			self.assertFalse(enabled("role_workspace_read"))

	def test_director_analytics_is_enabled_by_default_and_can_be_disabled_server_side(self):
		with patch("crm.fcrm.student_feature_flags.frappe.conf", {"crm_student_director_analytics_read_enabled": 1}):
			self.assertTrue(director_analytics_read_enabled())
		with patch("crm.fcrm.student_feature_flags.frappe.conf", {"crm_student_role_workspace_read_enabled": 1}):
			self.assertTrue(director_analytics_read_enabled())
		with patch("crm.fcrm.student_feature_flags.frappe.conf", {"crm_student_director_analytics_read_enabled": "false"}):
			self.assertFalse(director_analytics_read_enabled())
		with patch(
			"crm.fcrm.student_feature_flags.frappe.conf",
			{"crm_student_role_workspace_read_enabled": 1, "crm_student_director_analytics_read_enabled": 1},
		):
			self.assertTrue(director_analytics_read_enabled())

	def test_session_advertises_director_analytics_only_to_director_profile(self):
		with patch(
			"crm.fcrm.student_feature_flags.frappe.conf",
			{"crm_student_role_workspace_read_enabled": 1, "crm_student_director_analytics_read_enabled": 1},
		):
			self.assertTrue(_crm_feature_flags("admissions_director")["director_analytics_read"])
			self.assertFalse(_crm_feature_flags("sales")["director_analytics_read"])
			self.assertFalse(_crm_feature_flags(None)["director_analytics_read"])
