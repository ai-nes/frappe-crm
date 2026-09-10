"""Phase 1 contract tests for the closed Director analytics provider."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import director_analytics, role_workspaces
from crm.api.workspace_policy import WorkspacePolicyError, authorize_director_view, normalize_filters


class TestDirectorAnalytics(FrappeTestCase):
	def _policy(self):
		return frappe._dict(
			actor="director@example.com",
			profile="admissions_director",
			revision="policy",
			scope_version="campus-a",
			campuses=("Campus A",),
			capabilities=frozenset({"admissions.oversee"}),
		)

	def test_every_director_menu_route_has_a_closed_definition_and_readiness(self):
		for menu_id, readiness in director_analytics.DIRECTOR_ROUTE_READINESS.items():
			self.assertIn(
				(readiness["workspace"], readiness["view"]),
				director_analytics.DIRECTOR_VIEW_DEFINITIONS,
				menu_id,
			)
			self.assertIn(readiness["status"], {"ready", "unavailable"})

	def test_director_filters_are_view_specific_and_campus_cannot_expand_scope(self):
		policy = self._policy()
		self.assertEqual(
			normalize_filters("director-overview", {"campus": "Campus A"}, view="overview", policy=policy),
			{"campus": "Campus A"},
		)
		with self.assertRaises(WorkspacePolicyError):
			normalize_filters("director-overview", {"team": "X"}, view="overview", policy=policy)
		with self.assertRaises(WorkspacePolicyError):
			normalize_filters("director-overview", {"campus": "Campus B"}, view="overview", policy=policy)
		response = director_analytics._response("summary", None, "director-overview", "overview", {})
		self.assertEqual(
			response["filterSchema"][0],
			{"key": "period", "label": "Thời kỳ", "type": "select", "options": [], "default": None},
		)

	def test_director_summary_discloses_unreleased_student_contract_instead_of_zero(self):
		policy = self._policy()
		with (
			patch("crm.api.role_workspaces.role_workspace_read_enabled", return_value=True),
			patch("crm.api.role_workspaces.director_analytics_read_enabled", return_value=True),
			patch("crm.api.role_workspaces.derive_workspace_policy", return_value=policy),
			patch("crm.api.role_workspaces.get_encryption_key", return_value="test-key"),
			patch.object(director_analytics.frappe.db, "table_exists", return_value=False),
		):
			response = role_workspaces.get_workspace_summary("director-overview", "overview")
		self.assertEqual(response["contractStatus"], "unavailable")
		self.assertEqual(response["kpis"], [])
		self.assertEqual(response["definition"]["sources"], ["CRM Student"])
		self.assertEqual(response["scopeLabel"], director_analytics.DIRECTOR_SCOPE_LABEL)
		self.assertEqual(response["snapshotContext"]["watermarks"], {"CRM Student": "unreleased"})

	def test_director_facade_is_unavailable_when_director_canary_is_disabled(self):
		with (
			patch("crm.api.role_workspaces.role_workspace_read_enabled", return_value=True),
			patch("crm.api.role_workspaces.director_analytics_read_enabled", return_value=False),
			patch("crm.api.role_workspaces.derive_workspace_policy", return_value=self._policy()),
		):
			response = role_workspaces.get_workspace_summary("director-overview", "overview")
		self.assertEqual(response["contractStatus"], "unavailable")
		self.assertIsNone(response["snapshot"])

	def test_director_snapshot_binds_definition_and_timezone(self):
		policy = self._policy()
		context = {
			"definitionVersion": director_analytics.DIRECTOR_DEFINITION_VERSION,
			"timezone": "Asia/Ho_Chi_Minh",
			"asOf": "2026-08-28 00:00:00",
			"watermarks": {"CRM Lead": "2026-08-28 00:00:00"},
		}
		with patch("crm.api.role_workspaces.get_encryption_key", return_value="test-key"):
			snapshot = role_workspaces._mint_snapshot(
				policy, "director-overview", "overview", {}, context=context
			)
			payload = role_workspaces._validate_snapshot(
				snapshot, policy, "director-overview", "overview", {}
			)
		self.assertEqual(payload["definitionVersion"], director_analytics.DIRECTOR_DEFINITION_VERSION)
		self.assertEqual(payload["timezone"], "Asia/Ho_Chi_Minh")
		self.assertEqual(payload["asOf"], context["asOf"])
		self.assertEqual(payload["watermarks"], context["watermarks"])

	def test_one_director_snapshot_validates_for_summary_series_and_rows(self):
		policy = self._policy()
		context = {
			"definitionVersion": director_analytics.DIRECTOR_DEFINITION_VERSION,
			"timezone": "Asia/Ho_Chi_Minh",
			"asOf": "2026-08-28 00:00:00",
			"watermarks": {"CRM Lead": "2026-08-28 00:00:00"},
		}
		with patch("crm.api.role_workspaces.get_encryption_key", return_value="test-key"):
			snapshot = role_workspaces._mint_snapshot(
				policy, "director-overview", "overview", {}, context=context
			)
			for endpoint in ("summary", "series", "rows"):
				self.assertEqual(
					role_workspaces._validate_snapshot(snapshot, policy, "director-overview", "overview", {})[
						"asOf"
					],
					context["asOf"],
					endpoint,
				)

	def test_break_glass_requires_a_distinct_entitlement(self):
		with self.assertRaises(WorkspacePolicyError):
			authorize_director_view(self._policy(), "approvals", "break-glass")
		authorize_director_view(
			frappe._dict({**self._policy(), "capabilities": frozenset({"governance.break_glass.read"})}),
			"approvals",
			"break-glass",
		)

	def test_overview_uses_only_scoped_student_projection(self):
		policy = self._policy()
		with (
			patch.object(director_analytics.frappe.db, "table_exists", return_value=True),
			patch.object(director_analytics.frappe.db, "count", return_value=7) as count,
			patch.object(
				director_analytics.frappe.db,
				"get_all",
				return_value=[frappe._dict(student_stage="Connected", value=2)],
			),
			patch.object(director_analytics.frappe.db, "get_value", return_value="2026-08-28 00:00:00"),
		):
			response = director_analytics.get_summary(policy, "director-overview", "overview", {}, "snapshot")
		self.assertEqual(response["contractStatus"], "partial")
		self.assertIsNone(response["kpis"][0]["value"])
		self.assertEqual(response["kpis"][0]["nullReason"], "privacy_suppressed")
		self.assertIsNone(response["kpis"][1]["value"])
		self.assertEqual(response["kpis"][1]["nullReason"], "privacy_suppressed")
		self.assertEqual(count.call_args.kwargs["filters"], {"branch": ["in", ["Campus A"]]})

	def test_records_do_not_fall_back_to_contact_rows(self):
		policy = self._policy()
		student = frappe._dict(
			name="STU-1",
			student_name="A",
			branch="Campus A",
			major=None,
			student_stage="New",
			owner_staff=None,
			owning_team=None,
			modified="2026-08-28",
		)
		with (
			patch.object(director_analytics.frappe.db, "table_exists", return_value=True),
			patch.object(director_analytics.frappe.db, "get_all", return_value=[student]),
			patch.object(director_analytics.frappe.db, "get_value", return_value="2026-08-28"),
		):
			response = director_analytics.get_rows(policy, "director-records", "all", {}, "snapshot")
		self.assertEqual(response["contractStatus"], "partial")
		self.assertEqual(response["rows"][0]["drillDown"]["kind"], "student")
		self.assertEqual(
			response["rows"][0]["drillDown"]["resolver"],
			"crm.api.role_workspaces.resolve_workspace_row_detail",
		)
		self.assertNotIn("name", response["rows"][0])

	def test_small_aggregate_is_suppressed_and_row_token_is_scope_bound(self):
		policy = self._policy()
		with (
			patch.object(director_analytics.frappe.db, "table_exists", return_value=True),
			patch.object(director_analytics.frappe.db, "count", return_value=2),
			patch.object(
				director_analytics.frappe.db,
				"get_all",
				return_value=[frappe._dict(student_stage="Connected", value=2)],
			),
			patch.object(director_analytics.frappe.db, "get_value", return_value="2026-08-28"),
		):
			response = director_analytics.get_summary(policy, "director-overview", "overview", {}, "snapshot")
		self.assertIsNone(response["kpis"][0]["value"])
		self.assertEqual(response["kpis"][0]["nullReason"], "privacy_suppressed")
		token = director_analytics.mint_row_detail_token(policy, "snapshot", "STU-1")
		self.assertEqual(director_analytics.validate_row_detail_token(token, policy, "snapshot"), "STU-1")
		with self.assertRaises(frappe.PermissionError):
			director_analytics.validate_row_detail_token(
				token, frappe._dict({**policy, "scope_version": "other"}), "snapshot"
			)
