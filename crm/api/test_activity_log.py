from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import activity_log


class TestActivityLog(FrappeTestCase):
	def setUp(self):
		self.original_user = frappe.session.user

	def tearDown(self):
		frappe.set_user(self.original_user)

	def test_non_system_manager_denied_before_queries(self):
		with patch.object(activity_log, "get_session_role_flags", return_value={"is_system_manager": False}):
			with self.assertRaises(frappe.PermissionError):
				activity_log.get_activity_logs("segment")

	def test_invalid_module_rejected(self):
		with patch.object(activity_log, "get_session_role_flags", return_value={"is_system_manager": True}):
			with self.assertRaises(frappe.ValidationError):
				activity_log.get_activity_logs("not_a_module")

	def test_end_date_is_inclusive_for_date_input(self):
		start, end = activity_log._date_range("2026-09-01", "2026-09-10")
		self.assertEqual(start, datetime(2026, 9, 1))
		self.assertEqual(end, datetime(2026, 9, 11))

	def test_deleted_activity_is_critical(self):
		self.assertEqual(activity_log._severity_for("CRM Segment", None, "deleted"), "critical")

	def test_field_metadata_classifies_sensitive_changes(self):
		self.assertEqual(
			activity_log._field_metadata("CRM Lead", "owner_staff"),
			{"event_type": "assignment_changed", "category": "assignment"},
		)
		self.assertEqual(
			activity_log._field_metadata("User", "roles"),
			{"event_type": "permissions_changed", "category": "permissions"},
		)

	def test_role_filter_is_applied_as_one_owner_filter(self):
		version_log = {
			"event_id": "version:1",
			"occurred_at": "2026-09-10 10:00:00",
		}
		with (
			patch.object(activity_log, "get_session_role_flags", return_value={"is_system_manager": True}),
			patch.object(activity_log, "_version_logs", return_value=[version_log]) as version_logs,
			patch.object(activity_log, "_deletion_logs", return_value=[]),
			patch.object(activity_log, "_tracked_for_module", return_value=True),
			patch.object(
				frappe,
				"get_all",
				return_value=["actor@example.com"],
			),
		):
			result = activity_log.get_activity_logs("segment", role="System Manager")

		self.assertEqual(result["total"], 1)
		version_logs.assert_called_once_with(
			["CRM Segment"],
			["actor@example.com"],
			version_logs.call_args.args[2],
			version_logs.call_args.args[3],
		)

	def test_actor_search_matches_full_name_or_email(self):
		with patch.object(
			frappe,
			"get_all",
			return_value=["nguyen.hai.nam@fpt.edu.vn"],
		) as get_all:
			actor_ids = activity_log._find_actor_ids("Nguyễn Hải Nam")

		self.assertEqual(actor_ids, ["nguyen.hai.nam@fpt.edu.vn"])
		get_all.assert_called_once_with(
			"User",
			or_filters=[
				["full_name", "like", "%Nguyễn Hải Nam%"],
				["name", "like", "%Nguyễn Hải Nam%"],
			],
			pluck="name",
			limit_page_length=0,
		)

	def test_severity_filter_is_applied_before_pagination(self):
		logs = [
			{"event_id": "critical", "severity": "critical", "occurred_at": "2026-09-10 10:00:00"},
			{"event_id": "info", "severity": "info", "occurred_at": "2026-09-10 09:00:00"},
		]
		with (
			patch.object(activity_log, "get_session_role_flags", return_value={"is_system_manager": True}),
			patch.object(activity_log, "_version_logs", return_value=logs),
			patch.object(activity_log, "_deletion_logs", return_value=[]),
			patch.object(activity_log, "_tracked_for_module", return_value=True),
		):
			result = activity_log.get_activity_logs("segment", severity="critical", page_length=1)

		self.assertEqual(result["total"], 1)
		self.assertEqual(result["logs"][0]["event_id"], "critical")

	def test_all_module_combines_crm_sources_and_auth(self):
		with (
			patch.object(activity_log, "get_session_role_flags", return_value={"is_system_manager": True}),
			patch.object(activity_log, "_version_logs", return_value=[]),
			patch.object(activity_log, "_deletion_logs", return_value=[]),
			patch.object(activity_log, "_auth_activity_logs", return_value=[]),
			patch.object(activity_log, "_tracked_for_module", return_value=True),
		):
			result = activity_log.get_activity_logs("all")

		self.assertEqual(result["module"], "all")
		self.assertTrue(result["tracked"])
