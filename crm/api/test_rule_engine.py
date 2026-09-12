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
			fields=[
				"name",
				"status",
				"revision",
				"archived_at",
				"archived_by",
				"superseded_at",
				"superseded_by",
				"change_note",
			],
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
				frappe.db.set_value(
					"CRM Rule Version",
					version.name,
					{
						fieldname: version.get(fieldname)
						for fieldname in (
							"status",
							"revision",
							"archived_at",
							"archived_by",
							"superseded_at",
							"superseded_by",
							"change_note",
						)
					},
					update_modified=False,
				)
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

	def _assert_only_active_version(self, expected_name):
		active_versions = frappe.get_all("CRM Rule Version", filters={"status": "active"}, pluck="name")
		self.assertEqual(active_versions, [expected_name])
		self.assertEqual(
			frappe.db.get_single_value(rule_engine.SETTINGS_NAME, "active_rule_version", cache=False),
			expected_name,
		)

	def _activate_version_with_rule(self):
		rule = rule_engine.create_rule(self.version_id, 0, **self._rule())
		testing = rule_engine.update_rule_version(self.version_id, expected_revision=1, status="testing")
		active = rule_engine.activate_rule_version(
			self.version_id, self._settings_revision(), testing["revision"]
		)
		return rule, active

	def _assert_active_digest_consistent(self):
		catalog = rule_engine.get_active_rule_catalog()
		version = rule_engine.get_rule_version(self.version_id)
		settings_digest = frappe.db.get_single_value(
			rule_engine.SETTINGS_NAME, "active_ruleset_digest", cache=False
		)
		self.assertEqual(catalog["technical_revision"], version["revision"])
		self.assertEqual(catalog["ruleset_digest"], version["ruleset_digest"])
		self.assertEqual(catalog["ruleset_digest"], settings_digest)
		self.assertEqual(version["ruleset_revision"], str(version["revision"]))
		return catalog, version

	def test_version_starts_as_draft_with_empty_group_catalog(self):
		self.assertEqual(self.version["status"], "draft")
		self.assertEqual(self.version["group_catalog"], [])
		self.assertEqual(self.version["revision"], 0)

	def test_draft_group_catalog_crud_uses_parent_cas(self):
		created = rule_engine.create_rule_group(
			self.version_id, 0, "contact_governance", "Contact governance"
		)
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
		activated = rule_engine.activate_rule_version(
			self.version_id, self._settings_revision(), testing["revision"]
		)
		self.assertEqual(activated["status"], "active")
		self.assertRegex(activated["ruleset_digest"], r"^[a-f0-9]{64}$")
		self.assertEqual(
			frappe.db.get_single_value(rule_engine.SETTINGS_NAME, "active_rule_version", cache=False),
			self.version_id,
		)
		catalog = rule_engine.get_active_rule_catalog()
		self.assertEqual(
			set(catalog),
			{
				"schema",
				"rule_version",
				"technical_revision",
				"fact_catalog",
				"action_catalog",
				"rule_groups",
				"rules",
				"surface_outcome_mappings",
				"ruleset_digest",
			},
		)
		self.assertEqual(catalog["rule_version"], self.version_id)
		self.assertEqual(catalog["rules"][0]["rule_id"], rule["rule_id"])
		self.assertNotIn("rule_group", catalog["rules"][0])
		self.assertNotIn("feature_scope", catalog["rules"][0])
		self.assertNotIn("gate_outcome", catalog["rules"][0])
		self.assertNotIn("priority", catalog["rules"][0])
		self.assertNotIn("condition", catalog["rules"][0])
		self.assertNotIn("action", catalog["rules"][0])

	def test_immutable_catalog_uses_snapshot_revision_not_cas_revision(self):
		_, active = self._activate_version_with_rule()
		next_cas_revision = active["revision"] + 1
		frappe.db.set_value(
			"CRM Rule Version", self.version_id, "revision", next_cas_revision, update_modified=False
		)

		catalog = rule_engine.get_active_rule_catalog()
		self.assertEqual(catalog["technical_revision"], int(active["ruleset_revision"]))
		self.assertEqual(catalog["ruleset_digest"], active["ruleset_digest"])
		self.assertEqual(rule_engine.get_rule_version(self.version_id)["revision"], next_cas_revision)

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

		self._assert_only_active_version(self.version_id)
		for target_status in ("draft", "testing", "archived"):
			with self.assertRaises(frappe.ValidationError):
				rule_engine.update_rule_version(
					self.version_id,
					expected_revision=active["revision"],
					status=target_status,
				)
		self._assert_only_active_version(self.version_id)

	def test_nonactive_statuses_are_flexible_and_draft_can_be_activated_directly(self):
		rule = rule_engine.create_rule(self.version_id, 0, **self._rule())
		archived = rule_engine.update_rule_version(self.version_id, expected_revision=1, status="archived")
		self.assertEqual(archived["status"], "archived")
		self.assertEqual(frappe.db.get_value("CRM Rule", rule["name"], "status"), "archived")
		draft = rule_engine.update_rule_version(
			self.version_id,
			expected_revision=archived["revision"],
			status="draft",
		)
		self.assertEqual(frappe.db.get_value("CRM Rule", rule["name"], "status"), "draft")
		testing = rule_engine.update_rule_version(
			self.version_id,
			expected_revision=draft["revision"],
			status="testing",
		)
		archived = rule_engine.update_rule_version(
			self.version_id,
			expected_revision=testing["revision"],
			status="archived",
		)
		testing = rule_engine.update_rule_version(
			self.version_id,
			expected_revision=archived["revision"],
			status="testing",
		)
		draft = rule_engine.update_rule_version(
			self.version_id,
			expected_revision=testing["revision"],
			status="draft",
		)
		active = rule_engine.update_rule_version(
			self.version_id,
			expected_revision=draft["revision"],
			status="active",
			expected_settings_revision=draft["settings_revision"],
		)
		self.assertEqual(active["status"], "active")
		self.assertEqual(frappe.db.get_value("CRM Rule", rule["name"], "status"), "active")
		self._assert_only_active_version(self.version_id)

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

	def test_current_active_rule_crud_updates_catalog_digest_and_pointer(self):
		rule, active = self._activate_version_with_rule()
		starting_pointer_revision = self._settings_revision()
		self.assertEqual(rule_engine.get_rule(rule["name"])["status"], "active")

		created = rule_engine.create_rule(
			self.version_id,
			active["revision"],
			**self._rule(rule_id="FOLLOW-UP-001", group_code="student_support", outcome="PASS"),
		)
		self.assertEqual(created["status"], "active")
		catalog, version = self._assert_active_digest_consistent()
		self.assertEqual(version["revision"], active["revision"] + 1)
		self.assertEqual(self._settings_revision(), starting_pointer_revision + 1)
		self.assertIn("student_support", {group["code"] for group in catalog["rule_groups"]})

		with self.assertRaises(frappe.PermissionError):
			rule_engine.create_rule_group(self.version_id, version["revision"], "extra", "Extra")

		updated = rule_engine.update_rule(
			rule["name"],
			version["revision"],
			outcome="WAIT",
			business_reason_template="{action} is waiting on {rule_name}.",
		)
		self.assertEqual(updated["status"], "active")
		self.assertEqual(updated["outcome"], "WAIT")
		self.assertEqual(updated["revision"], 2)
		catalog, version = self._assert_active_digest_consistent()
		self.assertEqual(version["revision"], active["revision"] + 2)
		self.assertEqual(
			next(item for item in catalog["rules"] if item["rule_id"] == rule["rule_id"])["effect"][
				"outcome"
			],
			"WAIT",
		)

		toggled = rule_engine.set_rule_enabled(created["name"], version["revision"], False)
		self.assertFalse(toggled["enabled"])
		self.assertEqual(toggled["status"], "active")
		catalog, version = self._assert_active_digest_consistent()
		self.assertFalse(
			next(item for item in catalog["rules"] if item["rule_id"] == created["rule_id"])["enabled"]
		)

		deleted = rule_engine.delete_draft_rule(rule["name"], version["revision"])
		self.assertTrue(deleted["deleted"])
		catalog, version = self._assert_active_digest_consistent()
		self.assertEqual([item["rule_id"] for item in catalog["rules"]], [created["rule_id"]])

		previous_digest = catalog["ruleset_digest"]
		previous_pointer_revision = self._settings_revision()
		with self.assertRaises(frappe.ValidationError):
			rule_engine.delete_draft_rule(created["name"], version["revision"])
		catalog, version = self._assert_active_digest_consistent()
		self.assertEqual(catalog["ruleset_digest"], previous_digest)
		self.assertEqual(self._settings_revision(), previous_pointer_revision)
		self.assertEqual(version["revision"], deleted["revision"])
		self.assertTrue(frappe.db.exists("CRM Rule", created["name"]))

	def test_active_rule_rejects_invalid_and_stale_mutations_without_writes(self):
		rule, active = self._activate_version_with_rule()
		catalog_before, version_before = self._assert_active_digest_consistent()
		pointer_revision_before = self._settings_revision()

		with self.assertRaises(frappe.ValidationError):
			rule_engine.update_rule(rule["name"], active["revision"], outcome="NOT_A_GATE_OUTCOME")
		with self.assertRaises(frappe.ValidationError):
			rule_engine.set_rule_enabled(rule["name"], active["revision"] - 1, False)

		catalog_after, version_after = self._assert_active_digest_consistent()
		self.assertEqual(catalog_after["ruleset_digest"], catalog_before["ruleset_digest"])
		self.assertEqual(version_after["revision"], version_before["revision"])
		self.assertEqual(self._settings_revision(), pointer_revision_before)
		self.assertEqual(rule_engine.get_rule(rule["name"])["outcome"], "STOP")

	def test_direct_and_non_admin_active_rule_mutations_are_rejected(self):
		rule, active = self._activate_version_with_rule()
		previous_user = frappe.session.user
		try:
			doc = frappe.get_doc("CRM Rule", rule["name"])
			doc.outcome = "WAIT"
			with self.assertRaises(frappe.PermissionError):
				doc.save(ignore_permissions=True)

			version = frappe.get_doc("CRM Rule Version", self.version_id)
			version.revision += 1
			with self.assertRaises(frappe.PermissionError):
				version.save(ignore_permissions=True)

			frappe.set_user("Guest")
			with self.assertRaises(frappe.PermissionError):
				rule_engine.set_rule_enabled(rule["name"], active["revision"], False)
		finally:
			frappe.set_user(previous_user)

		catalog, version = self._assert_active_digest_consistent()
		self.assertEqual(catalog["rules"][0]["effect"]["outcome"], "STOP")
		self.assertEqual(version["revision"], active["revision"])

	def test_rule_admin_roles_manage_rules_without_direct_version_write_permission(self):
		rule = rule_engine.create_rule(self.version_id, 0, **self._rule(enabled=True))
		expected_version_revision = 1
		created_roles = []
		try:
			for role, enabled in (
				("System Manager", False),
				("Admissions Director", True),
				("Business Admin", False),
			):
				if not frappe.db.exists("Role", role):
					frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
						ignore_permissions=True
					)
					created_roles.append(role)
				email = f"rule-admin-{frappe.scrub(role)}-{frappe.generate_hash(length=8)}@example.com"
				user = frappe.get_doc(
					{
						"doctype": "User",
						"email": email,
						"first_name": "Rule Admin",
						"user_type": "System User",
						"send_welcome_email": 0,
						"roles": [{"role": role}],
					}
				).insert(ignore_permissions=True)
				try:
					frappe.set_user(user.name)
					self.assertIn(role, frappe.get_roles(user.name))
					self.assertFalse(frappe.has_permission("CRM Rule Version", "write", user=user.name))
					self.assertEqual(rule_engine.get_rule_version(self.version_id)["name"], self.version_id)
					self.assertEqual(
						rule_engine.list_rule_groups(self.version_id)["version_id"], self.version_id
					)

					updated = rule_engine.set_rule_enabled(rule["name"], expected_version_revision, enabled)
					self.assertEqual(updated["enabled"], enabled)
					expected_version_revision += 1
				finally:
					frappe.set_user("Administrator")
					frappe.delete_doc("User", user.name, force=True)
		finally:
			frappe.set_user("Administrator")
			for role in reversed(created_roles):
				frappe.delete_doc("Role", role, force=True)

	def test_clone_copies_full_independent_draft_snapshot(self):
		rule_engine.create_rule(self.version_id, 0, **self._rule(enabled=False))
		testing = rule_engine.update_rule_version(self.version_id, expected_revision=1, status="testing")
		rule_engine.activate_rule_version(self.version_id, self._settings_revision(), testing["revision"])
		clone_id = f"{self.version_id}-NEXT"
		clone = rule_engine.clone_rule_version(self.version_id, clone_id, "Next Test Version")
		self.assertEqual(clone["status"], "draft")
		self.assertEqual(
			clone["group_catalog"],
			[{"code": "contact_governance", "label": "Contact Governance", "enabled": True}],
		)
		cloned_rule = rule_engine.list_rules(clone_id)["rules"][0]
		self.assertFalse(cloned_rule["enabled"])
		self.assertEqual(cloned_rule["status"], "draft")

	def test_activation_cas_rejects_stale_pointer_and_immutable_lookup_accepts_archived(self):
		rule_engine.create_rule(self.version_id, 0, **self._rule())
		first_testing = rule_engine.update_rule_version(
			self.version_id, expected_revision=1, status="testing"
		)
		first = rule_engine.activate_rule_version(
			self.version_id, self._settings_revision(), first_testing["revision"]
		)
		clone_id = f"{self.version_id}-NEXT"
		rule_engine.clone_rule_version(self.version_id, clone_id)
		second_archived = rule_engine.update_rule_version(clone_id, expected_revision=0, status="archived")
		second = rule_engine.activate_rule_version(
			clone_id, self._settings_revision(), second_archived["revision"]
		)
		with self.assertRaises(frappe.ValidationError):
			rule_engine.activate_rule_version(self.version_id, 1, first["revision"])
		catalog = rule_engine.get_rule_catalog(self.version_id, first["ruleset_digest"])
		self.assertEqual(catalog["rule_version"], self.version_id)
		self.assertEqual(catalog["ruleset_digest"], first["ruleset_digest"])
		self.assertEqual(frappe.db.get_value("CRM Rule Version", self.version_id, "status"), "archived")
		archived_first = rule_engine.get_rule_version(self.version_id)
		self.assertEqual(archived_first["revision"], first["revision"] + 1)
		self.assertEqual(archived_first["ruleset_digest"], first["ruleset_digest"])
		with self.assertRaises(frappe.ValidationError):
			rule_engine.update_rule_version(
				self.version_id,
				expected_revision=first["revision"],
				status="draft",
			)
		self.assertEqual(frappe.db.get_value("CRM Rule Version", self.version_id, "status"), "archived")
		self.assertEqual(second["status"], "active")
		self._assert_only_active_version(clone_id)

	def test_group_reference_and_immutable_direct_writes_are_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			rule_engine.create_rule(
				self.version_id, 0, **self._rule(rule_id="BAD-GROUP-001", group_code="bad group")
			)

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
