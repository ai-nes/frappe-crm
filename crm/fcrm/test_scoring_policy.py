# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Tests for policy_revision/policy_hash versioning on CRM Score Template,
and the versioned crm-agents endpoint."""

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.scoring_policy import get_active_score_policy
from crm.fcrm.scoring_policy import get_active_policy


class TestScoringPolicyVersioning(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._previous_conf = frappe.conf.get("crm_agents_service_user")
		frappe.conf.crm_agents_service_user = "Administrator"
		self._deactivate_existing_active_templates()

	def tearDown(self):
		if self._previous_conf is None:
			frappe.conf.pop("crm_agents_service_user", None)
		else:
			frappe.conf.crm_agents_service_user = self._previous_conf
		for name in frappe.db.get_all(
			"CRM Score Template", filters={"template_name": ["like", "_Test SP%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Score Template", name, force=True)
		for name in frappe.db.get_all(
			"CRM Score Signal", filters={"label": ["like", "_Test SP%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Score Signal", name, force=True)

	def _deactivate_existing_active_templates(self):
		self._reactivate = []
		for name in frappe.db.get_all("CRM Score Template", filters={"status": "Active"}, pluck="name"):
			frappe.db.set_value("CRM Score Template", name, "status", "Inactive", update_modified=False)
			self._reactivate.append(name)
		self.addCleanup(self._restore_active_templates)

	def _restore_active_templates(self):
		for name in getattr(self, "_reactivate", []):
			frappe.db.set_value("CRM Score Template", name, "status", "Active", update_modified=False)

	def _make_signal(self, key, **overrides):
		fields = {
			"doctype": "CRM Score Signal",
			"signal_key": key,
			"label": key,
			"category": "Negative",
			"signal_type": "inactivity",
			"inactivity_days": 30,
		}
		fields.update(overrides)
		doc = frappe.get_doc(fields)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_template(self, name, signal_key, penalty_amount=5):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Score Template",
				"template_name": name,
				"status": "Active",
				"negative_rules": [{"signal": signal_key, "penalty_amount": penalty_amount}],
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def test_first_save_populates_revision_and_hash(self):
		signal = self._make_signal("_Test SP Signal A")
		template = self._make_template("_Test SP Template A", signal)

		doc = frappe.get_doc("CRM Score Template", template)
		self.assertEqual(doc.policy_revision, 1)
		self.assertTrue(doc.policy_hash)

	def test_editing_negative_rule_bumps_revision(self):
		signal = self._make_signal("_Test SP Signal B")
		template = self._make_template("_Test SP Template B", signal, penalty_amount=5)
		first_hash = frappe.db.get_value("CRM Score Template", template, "policy_hash")

		doc = frappe.get_doc("CRM Score Template", template)
		doc.negative_rules[0].penalty_amount = 10
		doc.save(ignore_permissions=True)

		doc.reload()
		self.assertEqual(doc.policy_revision, 2)
		self.assertNotEqual(doc.policy_hash, first_hash)

	def test_noop_save_does_not_bump_revision(self):
		"""compute_policy_hash() must be content-addressed, not
		identity-addressed: a no-op save must not bump policy_revision just
		because child rows were re-persisted with new row names."""
		signal = self._make_signal("_Test SP Signal E")
		template = self._make_template("_Test SP Template E", signal)
		first_revision = frappe.db.get_value("CRM Score Template", template, "policy_revision")
		first_hash = frappe.db.get_value("CRM Score Template", template, "policy_hash")

		doc = frappe.get_doc("CRM Score Template", template)
		doc.save(ignore_permissions=True)

		doc.reload()
		self.assertEqual(doc.policy_revision, first_revision)
		self.assertEqual(doc.policy_hash, first_hash)

	def test_signal_content_change_bumps_active_template(self):
		signal = self._make_signal("_Test SP Signal C", inactivity_days=30)
		template = self._make_template("_Test SP Template C", signal)
		first_revision = frappe.db.get_value("CRM Score Template", template, "policy_revision")

		signal_doc = frappe.get_doc("CRM Score Signal", signal)
		signal_doc.inactivity_days = 45
		signal_doc.save(ignore_permissions=True)

		second_revision = frappe.db.get_value("CRM Score Template", template, "policy_revision")
		self.assertEqual(second_revision, first_revision + 1)

	def test_editing_active_template_records_policy_changed_event(self):
		from unittest.mock import patch

		signal = self._make_signal("_Test SP Signal F")
		template = self._make_template("_Test SP Template F", signal, penalty_amount=5)

		doc = frappe.get_doc("CRM Score Template", template)
		doc.negative_rules[0].penalty_amount = 9
		with patch("crm.api.agent_events.record_agent_event") as mock_record:
			doc.save(ignore_permissions=True)

		mock_record.assert_called_once()
		args, _ = mock_record.call_args
		self.assertEqual(args[0], "scoring.policy_changed.v1")
		self.assertEqual(args[1].name, template)

	def test_noop_save_on_active_template_does_not_record_event(self):
		from unittest.mock import patch

		signal = self._make_signal("_Test SP Signal G")
		template = self._make_template("_Test SP Template G", signal)

		doc = frappe.get_doc("CRM Score Template", template)
		with patch("crm.api.agent_events.record_agent_event") as mock_record:
			doc.save(ignore_permissions=True)

		mock_record.assert_not_called()

	def test_editing_inactive_template_does_not_record_event(self):
		from unittest.mock import patch

		signal = self._make_signal("_Test SP Signal H")
		template = self._make_template("_Test SP Template H", signal, penalty_amount=5)
		doc = frappe.get_doc("CRM Score Template", template)
		doc.status = "Inactive"
		doc.save(ignore_permissions=True)

		doc.reload()
		doc.negative_rules[0].penalty_amount = 12
		with patch("crm.api.agent_events.record_agent_event") as mock_record:
			doc.save(ignore_permissions=True)

		mock_record.assert_not_called()

	def test_get_active_policy_none_when_no_active_template(self):
		self.assertIsNone(get_active_policy())

	def test_get_active_score_policy_returns_resolved_rules(self):
		signal = self._make_signal("_Test SP Signal D")
		self._make_template("_Test SP Template D", signal, penalty_amount=7)

		result = get_active_score_policy()

		self.assertIsNotNone(result["policy"])
		self.assertEqual(result["policy"]["policy_revision"], 1)
		self.assertEqual(len(result["policy"]["negative_rules"]), 1)
		self.assertEqual(result["policy"]["negative_rules"][0]["penalty_amount"], 7)

	def test_get_active_score_policy_requires_service_identity(self):
		frappe.conf.crm_agents_service_user = "someone-else@example.com"

		with self.assertRaises(frappe.PermissionError):
			get_active_score_policy()
