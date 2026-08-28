"""Contract tests for the session-scoped role workspace read facade."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import role_workspaces
from crm.api.workspace_policy import (
	WorkspacePolicyError,
	authorize_workspace,
	normalize_filters,
	route_for_menu_id,
)


class TestRoleWorkspaces(FrappeTestCase):
	def test_policy_denies_a_workspace_outside_the_actor_profile(self):
		policy = frappe._dict(profile="sales")
		with self.assertRaises(WorkspacePolicyError):
			authorize_workspace(policy, "system-api-keys", "inventory")

	def test_policy_accepts_canonical_workspace_view_and_parent_default(self):
		policy = frappe._dict(profile="sales")
		self.assertEqual(authorize_workspace(policy, "sales-records", "counseling"), "counseling")
		self.assertEqual(authorize_workspace(policy, "sales-urgent", None), "queue")
		self.assertEqual(authorize_workspace(policy, "sales-records", None), "new")
		with self.assertRaises(WorkspacePolicyError):
			authorize_workspace(policy, "sales-records", "queue")

	def test_lead_policy_does_not_retain_removed_cold_or_duplicate_menu_routes(self):
		for menu_id in ("lead_records_cold", "lead_duplicates"):
			with self.assertRaises(WorkspacePolicyError):
				route_for_menu_id("lead_sales", menu_id)

	def test_disabled_reader_returns_the_uniform_unavailable_contract(self):
		with patch("crm.api.role_workspaces.role_workspace_read_enabled", return_value=False):
			response = role_workspaces.get_workspace_summary("sales-urgent", "queue")

		self.assertEqual(response["contractStatus"], "unavailable")
		self.assertEqual(response["kpis"], [])
		self.assertIsNone(response["snapshot"])

	def test_unknown_or_client_controlled_filter_is_rejected(self):
		self.assertEqual(
			normalize_filters("sales-records", {"lifecycle": ["MQL", "Applicant"], "ownership": "mine"}),
			{"lifecycle": ["MQL", "Applicant"], "ownership": "mine"},
		)
		with self.assertRaises(WorkspacePolicyError):
			normalize_filters("sales-urgent", {"user": "Administrator"})
		with self.assertRaises(WorkspacePolicyError):
			normalize_filters("sales-urgent", {"status": "anything"})

	def test_snapshot_is_bound_to_actor_workspace_view_and_filters(self):
		with patch("crm.api.role_workspaces.get_encryption_key", return_value="test-key"):
			policy = frappe._dict(
				actor="sales@example.com", revision="role-workspace-v1", profile="sales", capabilities=frozenset(), scope_version="scope-a"
			)
			snapshot = role_workspaces._mint_snapshot(policy, "sales-urgent", "queue", {})
			self.assertEqual(
				role_workspaces._validate_snapshot(snapshot, policy, "sales-urgent", "queue", {})["actor"],
				"sales@example.com",
			)
			with self.assertRaises(frappe.PermissionError):
				role_workspaces._validate_snapshot(snapshot, policy, "sales-urgent", "queue", {"bucket": "cold"})
			with self.assertRaises(frappe.PermissionError):
				role_workspaces._validate_snapshot(
					snapshot,
					frappe._dict({**policy, "scope_version": "scope-b"}),
					"sales-urgent",
					"queue",
					{},
				)

	def test_badges_have_per_entry_snapshot_and_never_use_legacy_counts(self):
		policy = frappe._dict(
			actor="sales@example.com", revision="role-workspace-v1", profile="sales", capabilities=frozenset()
		)
		with (
			patch("crm.api.role_workspaces.role_workspace_read_enabled", return_value=True),
			patch("crm.api.role_workspaces.derive_workspace_policy", return_value=policy),
			patch("crm.api.role_workspaces.get_encryption_key", return_value="test-key"),
		):
			response = role_workspaces.get_workspace_badges()

		badge = response["badges"]["sales_immediate_contact"]
		self.assertEqual(response["contractStatus"], "ready")
		self.assertEqual(badge["contractStatus"], "migration_required")
		self.assertIn("snapshot", badge)
		self.assertNotIn("legacyContactCount", badge)

	def test_export_keeps_legacy_providers_migration_required(self):
		policy = frappe._dict(actor="sales@example.com", revision="role-workspace-v1", profile="sales", capabilities=frozenset(), scope_version="scope-a")
		with (
			patch("crm.api.role_workspaces.role_workspace_read_enabled", return_value=True),
			patch("crm.api.role_workspaces.derive_workspace_policy", return_value=policy),
			patch("crm.api.role_workspaces.get_encryption_key", return_value="test-key"),
		):
			response = role_workspaces.get_workspace_export("sales-urgent", "queue")
		self.assertEqual(response["contractStatus"], "migration_required")
		self.assertIsNone(response["download"])

	def test_director_canary_does_not_disable_sales_workspace_facade(self):
		policy = frappe._dict(actor="sales@example.com", revision="role-workspace-v1", profile="sales", capabilities=frozenset(), scope_version="scope-a")
		with (
			patch("crm.api.role_workspaces.role_workspace_read_enabled", return_value=True),
			patch("crm.api.role_workspaces.director_analytics_read_enabled", return_value=False),
			patch("crm.api.role_workspaces.derive_workspace_policy", return_value=policy),
			patch("crm.api.role_workspaces.get_encryption_key", return_value="test-key"),
		):
			response = role_workspaces.get_workspace_summary("sales-urgent", "queue")
		self.assertEqual(response["contractStatus"], "migration_required")

	def test_row_detail_rechecks_current_student_campus(self):
		policy = frappe._dict(actor="director@example.com", profile="admissions_director", campuses=("Campus A",), scope_version="scope-a")
		with (
			patch("crm.api.role_workspaces._request", return_value=(policy, "all", {}, "snapshot")),
			patch("crm.api.director_analytics.validate_row_detail_token", return_value="STU-1"),
			patch("crm.api.role_workspaces.frappe.db.get_value", return_value="Campus B"),
		):
			with self.assertRaises(frappe.PermissionError):
				role_workspaces.resolve_workspace_row_detail("director-records", "all", snapshot="snapshot", token="opaque")
