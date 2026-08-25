from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import admissions_analytics


class TestAdmissionsAnalyticsAccess(FrappeTestCase):
	def test_system_manager_is_denied_copilot_analytics(self):
		with patch.object(
			admissions_analytics,
			"get_session_role_flags",
			return_value={"is_crm_user": True, "is_system_manager": True},
		):
			with self.assertRaises(frappe.PermissionError):
				admissions_analytics._require_role()

	def test_mixed_system_manager_role_is_denied_before_role_lookup(self):
		with patch.object(
			admissions_analytics,
			"get_session_role_flags",
			side_effect=frappe.PermissionError,
		), patch.object(admissions_analytics.frappe, "get_roles") as get_roles:
			with self.assertRaises(frappe.PermissionError):
				admissions_analytics._require_role()
		get_roles.assert_not_called()
