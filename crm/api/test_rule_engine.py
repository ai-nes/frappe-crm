"""Integration coverage for the versioned CRM Rule admin and runtime APIs."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import rule_engine


class TestCrmRuleVersionApi(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.version_id = f"TEST-{frappe.generate_hash(length=10).upper()}"
		self.previous_active_versions = frappe.get_all(
			"CRM Rule Version",
			filters={"is_active": 1},
			fields=["name", "is_active"],
		)
		self.version = rule_engine.create_rule_version(self.version_id, "Test Rule Version")

	def tearDown(self):
		frappe.set_user("Administrator")
		for version in frappe.get_all(
			"CRM Rule Version", filters={"version_id": ["like", "TEST-%"]}, pluck="name"
		):
			frappe.db.delete("CRM Rule", {"rule_version": version})
			frappe.db.delete("CRM Rule Version", version)
		for version in self.previous_active_versions:
			if frappe.db.exists("CRM Rule Version", version.name):
				frappe.db.set_value(
					"CRM Rule Version", version.name, "is_active", version.is_active, update_modified=False
				)
		frappe.db.commit()

	def _rule(self, **overrides):
		value = {
			"rule_id": "CALL-CONSENT-001",
			"rule_group": "CONSENT",
			"rule_name": "Block opted-out calls",
			"feature_scope": "nba",
			"rule_type": "GUARDRAIL",
			"gate_outcome": "STOP",
			"priority": 100,
			"action": "BLOCK_CALL",
			"target_actions": ["CALL"],
			"condition": {"all": [{"fact": "student.is_opted_out", "op": "is_true"}]},
		}
		value.update(overrides)
		return value

	def test_empty_version_cannot_be_published(self):
		with self.assertRaises(frappe.ValidationError):
			rule_engine.publish_rule_version(self.version_id, 0)

	def test_version_identity_cannot_be_blank(self):
		with self.assertRaises(frappe.ValidationError):
			rule_engine.create_rule_version("", "Unnamed Rule Version")
		with self.assertRaises(frappe.ValidationError):
			rule_engine.create_rule_version(
			f"TEST-{frappe.generate_hash(length=10).upper()}", "   "
		)

	def test_new_publish_keeps_previous_version_published_but_inactive(self):
		rule_engine.create_rule(self.version_id, 0, **self._rule())
		rule_engine.publish_rule_version(self.version_id, 1)
		clone_id = f"{self.version_id}-NEXT"
		clone = rule_engine.clone_rule_version(self.version_id, clone_id, "Next Test Version")
		rule_engine.publish_rule_version(clone["name"], 0)

		versions = rule_engine.list_rule_versions()["versions"]
		old = next(row for row in versions if row["version_id"] == self.version_id)
		current = next(row for row in versions if row["version_id"] == clone_id)
		self.assertEqual(old["status"], "published")
		self.assertFalse(old["is_active"])
		self.assertTrue(current["is_active"])
		catalog = rule_engine.get_active_rule_catalog("nba")
		self.assertEqual(catalog["version_id"], clone_id)
		self.assertEqual([row["rule_id"] for row in catalog["rules"]], ["CALL-CONSENT-001"])

	def test_parent_revision_rejects_stale_mutation_and_duplicate_rule_id(self):
		rule_engine.create_rule(self.version_id, 0, **self._rule())
		with self.assertRaises(frappe.ValidationError):
			rule_engine.create_rule(self.version_id, 0, **self._rule(rule_id="EMAIL-CONSENT-001"))
		with self.assertRaises(frappe.DuplicateEntryError):
			rule_engine.create_rule(self.version_id, 1, **self._rule())

	def test_draft_crud_returns_version_and_group_views(self):
		first = rule_engine.create_rule(self.version_id, 0, **self._rule())
		second = rule_engine.create_rule(
			self.version_id,
			1,
			**self._rule(
				rule_id="APPLICATION-DOCUMENT-001",
				rule_group="ADMISSION_DATA",
				rule_name="Require application documents",
				gate_outcome="WAIT",
				action="REQUEST_DOCUMENT",
				target_actions=["REQUEST_DOCUMENT"],
			),
		)
		updated = rule_engine.update_rule(
			first["name"],
			2,
			rule_name="Block opted-out calls immediately",
		)

		self.assertEqual(updated["rule_name"], "Block opted-out calls immediately")
		self.assertEqual(updated["version_id"], self.version_id)
		self.assertEqual(
			rule_engine.list_rule_groups(self.version_id)["groups"],
			[
				{"group_id": "ADMISSION_DATA", "label": "ADMISSION_DATA", "count": 1},
				{"group_id": "CONSENT", "label": "CONSENT", "count": 1},
			],
		)
		self.assertEqual(
			rule_engine.list_rules(self.version_id, rule_group="CONSENT")["rules"][0]["name"],
			first["name"],
		)
		deleted = rule_engine.delete_draft_rule(second["name"], 3)
		self.assertTrue(deleted["deleted"])


	def test_published_version_is_immutable_and_active_version_cannot_be_archived(self):
		rule_engine.create_rule(self.version_id, 0, **self._rule())
		rule_engine.publish_rule_version(self.version_id, 1)
		with self.assertRaises(frappe.PermissionError):
			rule_engine.update_rule_version(self.version_id, 2, version_name="Changed")
		with self.assertRaises(frappe.PermissionError):
			rule_engine.archive_rule_version(self.version_id, 2, "not allowed")
