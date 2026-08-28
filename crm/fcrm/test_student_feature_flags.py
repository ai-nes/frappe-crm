from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_feature_flags import enabled, role_workspace_read_enabled


class TestStudentFeatureFlags(FrappeTestCase):
	def test_role_workspace_reader_is_disabled_by_default(self):
		with patch("crm.fcrm.student_feature_flags.frappe.conf", {}):
			self.assertFalse(role_workspace_read_enabled())

	def test_role_workspace_reader_uses_only_its_server_owned_key(self):
		with patch("crm.fcrm.student_feature_flags.frappe.conf", {"crm_student_role_workspace_read_enabled": 1}):
			self.assertTrue(role_workspace_read_enabled())
		with patch("crm.fcrm.student_feature_flags.frappe.conf", {"crm_student_role_workspace_read_enabled": "false"}):
			self.assertFalse(enabled("role_workspace_read"))
