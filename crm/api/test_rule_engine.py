"""Integration coverage for the versioned CRM Rule control plane."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import rule_engine


class TestCrmRuleVersionApi(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.version_id = f"TEST-{frappe.generate_hash(length=10).upper()}"
		self.previous_settings = frappe.db.get_singles_dict(rule_engine.SETTINGS_NAME, cast=True)
		self.previous_versions = frappe.get_all(
			"CRM Rule Version",
			filters={"status": "active"},
			fields=["name", "status"],
		)
		self.previous_service_user = frappe.conf.get("crm_agents_service_user")
		frappe.conf.crm_agents_service_user = "Administrator"
		self.version = rule_engine.create_rule_version(self.version_id, "Test Rule Version")

	def tearDown(self):
		frappe.set_user("Administrator")
		for version in frappe.get_all(
			"CRM Rule Version", filters={"version_id": ["like", "TEST-%"]}, pluck="name"
		):
			frappe.db.delete("CRM Rule", {"rule_version": version})
			frappe.db.delete("CRM Rule Version", version)
		for version in self.previous_versions:
			if frappe.db.exists("CRM Rule Version", version.name):
				frappe.db.set_value("CRM Rule Version", version.name, "status", version.status, update_modified=False)
				frappe.db.set_value(
					"CRM Rule",
					{"rule_version": version.name, "status": ["in", ["superseded", "archived"]]},
					"status",
					"active",
					update_modified=False,
				)
		if self.previous_settings:
			frappe.db.set_single_value(
				rule_engine.SETTINGS_NAME, dict(self.previous_settings), update_modified=False
			)
		else:
			frappe.db.delete("Singles", {"doctype": rule_engine.SETTINGS_NAME})
		if self.previous_service_user is None:
			try:
				del frappe.conf.crm_agents_service_user
			except AttributeError:
				frappe.conf.crm_agents_service_user = None
		else:
			frappe.conf.crm_agents_service_user = self.previous_service_user
		frappe.db.commit()

	def _rule(self, **overrides):
		value = {
			"rule_id": "CALL-CONSENT-001",
			"group_code": "contact_governance",
			"rule_name": "Block opted-out calls",
			"feature": "nba",
			"rule_type": "GUARDRAIL",
			"outcome": "STOP",
			"precedence": 100,
			"unknown_policy": "WAIT",
			"reason_code": "CONTACT_CONSENT",
			"business_reason_template": "{action} is blocked by {rule_name}.",
			"target_actions": ["CALL"],
			"conditions": [
				{"fact": "student.is_opted_out", "operator": "is_true"},
			],
			"enabled": True,
		}
		value.update(overrides)
		return value

	def _settings_revision(self):
		return frappe.db.get_single_value(rule_engine.SETTINGS_NAME, "pointer_revision", cache=False) or 0

	def test_version_starts_as_draft_with_empty_group_catalog(self):
		self.assertEqual(self.version["status"], "draft")
		self.assertEqual(self.version["group_catalog"], [])
		self.assertEqual(self.version["revision"], 0)

	def test_draft_group_catalog_crud_uses_parent_cas(self):
		created = rule_engine.create_rule_group(self.version_id, 0, "contact_governance", "Contact governance")
		self.assertEqual(created["revision"], 1)
		updated = rule_engine.update_rule_group(
			self.version_id, "contact_governance", 1, label="Contact governance rules", enabled=True
		)
		self.assertEqual(updated["revision"], 2)
		with self.assertRaises(frappe.ValidationError):
			rule_engine.update_rule_group(self.version_id, "contact_governance", 1, enabled=False)
		deleted = rule_engine.delete_rule_group(self.version_id, "contact_governance", 2)
		self.assertTrue(deleted["deleted"])

	def test_activation_builds_complete_catalog_and_authoritative_pointer(self):
		rule = rule_engine.create_rule(self.version_id, 0, **self._rule())
		testing = rule_engine.update_rule_version(self.version_id, expected_revision=1, status="testing")
		activated = rule_engine.activate_rule_version(self.version_id, self._settings_revision(), testing["revision"])
		self.assertEqual(activated["status"], "active")
		self.assertRegex(activated["ruleset_digest"], r"^[a-f0-9]{64}$")
		self.assertEqual(
			frappe.db.get_single_value(rule_engine.SETTINGS_NAME, "active_rule_version", cache=False),
			self.version_id,
		)
		catalog = rule_engine.get_active_rule_catalog()
		self.assertEqual(set(catalog), {
			"schema",
			"rule_version",
			"technical_revision",
			"fact_catalog",
			"action_catalog",
			"rule_groups",
			"rules",
			"surface_outcome_mappings",
			"ruleset_digest",
		})
		self.assertEqual(catalog["rule_version"], self.version_id)
		self.assertEqual(catalog["rules"][0]["rule_id"], rule["rule_id"])
		self.assertNotIn("rule_group", catalog["rules"][0])
		self.assertNotIn("feature_scope", catalog["rules"][0])
		self.assertNotIn("gate_outcome", catalog["rules"][0])
		self.assertNotIn("priority", catalog["rules"][0])
		self.assertNotIn("condition", catalog["rules"][0])
		self.assertNotIn("action", catalog["rules"][0])

	def test_status_put_follows_draft_testing_active_archived_lifecycle(self):
		rule_engine.create_rule(self.version_id, 0, **self._rule())
		testing = rule_engine.update_rule_version(
			self.version_id,
			expected_revision=1,
			status="testing",
		)
		self.assertEqual(testing["status"], "testing")
		self.assertEqual(testing["revision"], 2)
		active = rule_engine.update_rule_version(
			self.version_id,
			expected_revision=testing["revision"],
			status="active",
			expected_settings_revision=testing["settings_revision"],
		)
		self.assertEqual(active["status"], "active")
		self.assertTrue(active["is_active"])

		with self.assertRaises(frappe.ValidationError):
			rule_engine.update_rule_version(
				self.version_id,
				expected_revision=active["revision"],
				status="draft",
			)

	def test_status_put_allows_testing_back_to_draft_and_rejects_direct_draft_active(self):
		rule_engine.create_rule(self.version_id, 0, **self._rule())
		with self.assertRaises(frappe.ValidationError):
			rule_engine.activate_rule_version(self.version_id, self._settings_revision(), 1)
		with self.assertRaises(frappe.ValidationError):
			rule_engine.update_rule_version(self.version_id, expected_revision=1, status="active")
		testing = rule_engine.update_rule_version(self.version_id, expected_revision=1, status="testing")
		draft = rule_engine.update_rule_version(
			self.version_id,
			expected_revision=testing["revision"],
			status="draft",
		)
		self.assertEqual(draft["status"], "draft")

	def test_activation_accepts_global_rule_scope_for_the_complete_catalog(self):
		rule = rule_engine.create_rule(
			self.version_id,
			0,
			**self._rule(
				rule_id="ALL-OPT-OUT-001",
				feature="all",
				conditions=[{"fact": "student.is_opted_out", "operator": "is_true"}],
				target_actions=[],
				business_reason_template="AI work is blocked by {rule_name}.",
			),
		)
		testing = rule_engine.update_rule_version(self.version_id, expected_revision=1, status="testing")
		rule_engine.activate_rule_version(self.version_id, self._settings_revision(), testing["revision"])
		catalog = rule_engine.get_active_rule_catalog()
		self.assertEqual(catalog["rules"][0]["rule_id"], rule["rule_id"])
		self.assertEqual(catalog["rules"][0]["feature"], "all")

	def test_editing_a_draft_rule_rebuilds_the_next_catalog_from_doctype_data(self):
		rule = rule_engine.create_rule(self.version_id, 0, **self._rule())
		updated = rule_engine.update_rule(
			rule["name"],
			1,
			outcome="WAIT",
			business_reason_template="{action} is waiting on {rule_name}.",
		)

		self.assertEqual(updated["outcome"], "WAIT")
		self.assertEqual(updated["business_reason_template"], "{action} is waiting on {rule_name}.")
		self.assertEqual(rule_engine.list_rules(self.version_id)["rules"][0]["outcome"], "WAIT")

	def test_list_rules_search_matches_target_actions(self):
		rule_engine.create_rule(self.version_id, 0, **self._rule(target_actions=["SEND_EMAIL"]))

		result = rule_engine.list_rules(self.version_id, search="SEND_EMAIL")

		self.assertEqual(len(result["rules"]), 1)
		self.assertEqual(result["rules"][0]["target_actions"], ["SEND_EMAIL"])

	def test_set_rule_enabled_toggles_only_the_draft_rule_and_bumps_parent_revision(self):
		rule = rule_engine.create_rule(self.version_id, 0, **self._rule(enabled=True))
		updated = rule_engine.set_rule_enabled(rule["name"], 1, False)
		self.assertFalse(updated["enabled"])
		self.assertEqual(updated["revision"], 1)
		self.assertEqual(rule_engine.get_rule_version(self.version_id)["revision"], 2)
		testing = rule_engine.update_rule_version(self.version_id, expected_revision=2, status="testing")
		with self.assertRaises(frappe.PermissionError):
			rule_engine.set_rule_enabled(rule["name"], testing["revision"], True)

	def test_clone_copies_full_independent_draft_snapshot(self):
		rule_engine.create_rule(self.version_id, 0, **self._rule(enabled=False))
		testing = rule_engine.update_rule_version(self.version_id, expected_revision=1, status="testing")
		rule_engine.activate_rule_version(self.version_id, self._settings_revision(), testing["revision"])
		clone_id = f"{self.version_id}-NEXT"
		clone = rule_engine.clone_rule_version(self.version_id, clone_id, "Next Test Version")
		self.assertEqual(clone["status"], "draft")
		self.assertEqual(clone["group_catalog"], [{"code": "contact_governance", "label": "Contact Governance", "enabled": True}])
		cloned_rule = rule_engine.list_rules(clone_id)["rules"][0]
		self.assertFalse(cloned_rule["enabled"])
		self.assertEqual(cloned_rule["status"], "draft")

	def test_activation_cas_rejects_stale_pointer_and_immutable_lookup_accepts_archived(self):
		rule_engine.create_rule(self.version_id, 0, **self._rule())
		first_testing = rule_engine.update_rule_version(self.version_id, expected_revision=1, status="testing")
		first = rule_engine.activate_rule_version(self.version_id, self._settings_revision(), first_testing["revision"])
		clone_id = f"{self.version_id}-NEXT"
		rule_engine.clone_rule_version(self.version_id, clone_id)
		second_testing = rule_engine.update_rule_version(clone_id, expected_revision=0, status="testing")
		second = rule_engine.activate_rule_version(clone_id, self._settings_revision(), second_testing["revision"])
		with self.assertRaises(frappe.ValidationError):
			rule_engine.activate_rule_version(self.version_id, 1, first["revision"])
		catalog = rule_engine.get_rule_catalog(self.version_id, first["ruleset_digest"])
		self.assertEqual(catalog["rule_version"], self.version_id)
		self.assertEqual(catalog["ruleset_digest"], first["ruleset_digest"])
		self.assertEqual(frappe.db.get_value("CRM Rule Version", self.version_id, "status"), "archived")
		self.assertEqual(second["status"], "active")

	def test_group_reference_and_immutable_direct_writes_are_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			rule_engine.create_rule(self.version_id, 0, **self._rule(
				rule_id="BAD-GROUP-001", group_code="bad group"
			))

	def test_management_and_catalog_reads_are_separated_by_identity(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			rule_engine.list_rule_versions()
		with self.assertRaises(frappe.PermissionError):
			rule_engine.get_active_rule_catalog()

	def test_crm_rule_admin_roles_can_manage_the_control_plane(self):
		previous_user = frappe.session.user
		try:
			frappe.session.user = "rules-manager@example.com"
			for role in ("System Manager", "Admissions Director", "Business Admin"):
				with patch.object(frappe, "get_roles", return_value=[role]):
					rule_engine._require_admin()
			with patch.object(frappe, "get_roles", return_value=["Sale"]):
				with self.assertRaises(frappe.PermissionError):
					rule_engine._require_admin()
		finally:
			frappe.session.user = previous_user
