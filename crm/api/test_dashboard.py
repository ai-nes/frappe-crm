from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.dashboard import get_sidebar_badge_counts


class TestSidebarBadgeCounts(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	@patch("crm.api.dashboard.role_workspace_read_enabled", return_value=False)
	@patch("crm.api.dashboard.frappe.get_roles", return_value=["Lead Sales"])
	@patch("crm.api.dashboard.frappe.get_list")
	@patch("crm.api.dashboard.frappe.db.table_exists")
	def test_sla_badges_use_permission_aware_counts_with_list_filters(
		self, table_exists, get_list, _get_roles, _workspace_read_enabled
	):
		table_exists.side_effect = lambda doctype: doctype == "CRM Student SLA Attempt"
		get_list.side_effect = [[{"count": 2}], [{"count": 4}]]

		badges = get_sidebar_badge_counts()

		self.assertEqual(badges["urgentSlaCount"], 2)
		self.assertEqual(badges["teamSlaBreachedCount"], 4)
		self.assertEqual(
			get_list.call_args_list,
			[
				(
					("CRM Student SLA Attempt",),
					{
						"filters": {"status": "open"},
						"fields": ["count(name) as count"],
						"limit_page_length": 1,
					},
				),
				(
					("CRM Student SLA Attempt",),
					{
						"filters": {"status": ["in", ["breached", "escalated"]]},
						"fields": ["count(name) as count"],
						"limit_page_length": 1,
					},
				),
			],
		)
