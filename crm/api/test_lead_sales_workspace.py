"""Focused contracts for Lead Sale workspace reader boundaries."""

from importlib import import_module
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

workspace = import_module("crm.api.lead_sales_workspace")


class TestLeadSalesWorkspace(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		for doctype, filters in (
			("CRM Student", {"full_name": ["like", "_Test LSW%"]}),
			("CRM Staff", {"full_name": ["like", "_Test LSW%"]}),
			("User", {"first_name": ["like", "_Test LSW%"]}),
			("CRM Team", {"team_name": ["like", "_Test LSW%"]}),
			("CRM Department", {"department_name": ["like", "_Test LSW%"]}),
			("CRM Campus", {"campus_name": ["like", "_Test LSW%"]}),
		):
			for name in frappe.db.get_all(doctype, filters=filters, pluck="name"):
				frappe.delete_doc(doctype, name, force=True)

	def _make_campus(self, label):
		return (
			frappe.get_doc({"doctype": "CRM Campus", "campus_name": label})
			.insert(ignore_permissions=True)
			.name
		)

	def _make_team(self, label, campus):
		return (
			frappe.get_doc(
				{
					"doctype": "CRM Team",
					"team_name": label,
					"team_type": "Sales",
					"campus": campus,
					"is_active": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _make_lead(self, label, campus, department, team):
		email = f"{frappe.scrub(label)}@example.test"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": label,
				"send_welcome_email": 0,
				"roles": [{"role": "Lead Sale"}],
			}
		).insert(ignore_permissions=True)
		staff = frappe.get_doc(
			{
				"doctype": "CRM Staff",
				"full_name": label,
				"user": email,
				"campus": campus,
				"department": department,
			}
		)
		staff.append("team_memberships", {"team": team, "function": "Lead Sale", "term": "", "is_primary": 1})
		return email, staff.insert(ignore_permissions=True).name

	def _make_student(self, label, owner, team):
		student = frappe.get_doc(
			{"doctype": "CRM Student", "full_name": label, "phone": "0900000000", "student_stage": "New"}
		)
		student.insert(ignore_permissions=True)
		student.db_set("owner_staff", owner)
		student.db_set("owning_team", team)
		return student

	def test_team_oversee_capability_is_required(self):
		previous_user = frappe.session.user
		frappe.set_user("reader@example.test")
		with (
			patch.object(frappe, "get_roles", return_value=["Sale"]),
			patch.object(workspace, "capabilities_for_roles", return_value=frozenset()),
		):
			try:
				self.assertRaises(frappe.PermissionError, workspace.get_team_dashboard)
			finally:
				frappe.set_user(previous_user)

	def test_period_rejects_client_defined_ranges(self):
		self.assertRaises(frappe.ValidationError, workspace._period, "2026-01-01")

	def test_dashboard_endpoint_excludes_sibling_team_student(self):
		"""Exercise the endpoint under Frappe's real row permission hook."""
		campus = self._make_campus("_Test LSW Campus")
		department = (
			frappe.get_doc(
				{"doctype": "CRM Department", "department_name": "_Test LSW Department", "campus": campus}
			)
			.insert(ignore_permissions=True)
			.name
		)
		primary_team = self._make_team("_Test LSW Primary", campus)
		sibling_team = self._make_team("_Test LSW Sibling", campus)
		primary_user, primary_staff = self._make_lead(
			"_Test LSW Primary Lead", campus, department, primary_team
		)
		_sibling_user, sibling_staff = self._make_lead(
			"_Test LSW Sibling Lead", campus, department, sibling_team
		)
		self._make_student("_Test LSW Primary Student", primary_staff, primary_team)
		self._make_student("_Test LSW Sibling Student", sibling_staff, sibling_team)

		frappe.set_user(primary_user)
		try:
			response = workspace.get_team_dashboard()
		finally:
			frappe.set_user("Administrator")

		visible_owners = {row["owner_staff"] for row in response["workload"]}
		self.assertIn(primary_staff, visible_owners)
		self.assertNotIn(sibling_staff, visible_owners)

	@patch("crm.api.lead_sales_workspace.get_encryption_key", return_value="test-key")
	def test_action_cursor_is_bound_to_actor_and_status(self, _key):
		cursor = workspace._encode_cursor(20, "lead@example.test", "open")
		self.assertEqual(workspace._decode_cursor(cursor, "lead@example.test", "open"), 20)
		self.assertRaises(
			frappe.PermissionError, workspace._decode_cursor, cursor, "sibling@example.test", "open"
		)
		self.assertRaises(
			frappe.PermissionError, workspace._decode_cursor, cursor, "lead@example.test", "completed"
		)

	@patch("crm.api.lead_sales_workspace._generated", return_value="2026-08-28 00:00:00")
	@patch("crm.api.lead_sales_workspace._require_team_oversee")
	@patch("crm.api.lead_sales_workspace._count")
	@patch("crm.api.lead_sales_workspace._grouped_count")
	def test_dashboard_uses_declared_student_and_sla_filters(
		self, grouped_count, count, _require, _generated
	):
		grouped_count.side_effect = [
			[frappe._dict(owner_staff="STAFF-1", count=2)],
			[frappe._dict(status="breached", count=1)],
		]
		count.side_effect = [2, 1, 1]

		response = workspace.get_team_dashboard()

		self.assertEqual(
			response["kpis"], {"active_students": 2, "unassigned_students": 1, "breached_sla": 1}
		)
		self.assertEqual(response["definition"]["period"], "current")
		self.assertEqual(response["workload"], [{"owner_staff": "STAFF-1", "count": 2}])
		self.assertEqual(response["sla_buckets"], [{"status": "breached", "count": 1}])
		self.assertEqual(
			count.call_args_list,
			[
				(("CRM Student", {"student_stage": ["not in", ["Connected", "Disqualified"]]}),),
				(("CRM Student", {"owner_staff": ["is", "not set"]}),),
				(
					("CRM Student SLA Attempt", {"status": ["in", ["breached", "escalated"]]}),
					{"ignore_permissions": True},
				),
			],
		)

	@patch("crm.api.lead_sales_workspace.frappe.get_list")
	@patch("crm.api.lead_sales_workspace._require_team_oversee", return_value="lead@example.test")
	def test_team_action_reader_never_accepts_staff_or_team_scope(self, _require, get_list):
		get_list.side_effect = [[], []]
		response = workspace.list_team_actions(status="open", page_size=20)

		self.assertEqual(response["rows"], [])
		action_call = get_list.call_args_list[0]
		self.assertEqual(action_call.args[0], "CRM Action Item")
		self.assertEqual(action_call.kwargs["filters"], [["state", "in", workspace._OPEN_ACTION_STATES]])
		self.assertNotIn("team", action_call.kwargs["filters"])
		self.assertNotIn("staff", action_call.kwargs["filters"])

	def test_safe_policy_projection_excludes_approval_and_mutation_fields(self):
		with (
			patch("crm.api.lead_sales_workspace._require_team_oversee"),
			patch("crm.api.lead_sales_workspace.frappe.get_list", return_value=[]),
			patch("crm.api.lead_sales_workspace.frappe.get_all", return_value=[]) as get_all,
		):
			workspace.get_readonly_sla_policies()
			fields = get_all.call_args.kwargs["fields"]
			self.assertNotIn("approved_by", fields)
			self.assertNotIn("approved_at", fields)
			self.assertNotIn("pause_reasons", fields)
			self.assertEqual(get_all.call_args.kwargs["filters"], {"status": "active"})
