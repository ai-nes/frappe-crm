"""Mutual exclusion between the NBA Evaluation runtime and the legacy generator.

When ``crm_nba_evaluation_runtime_enabled`` is truthy the durable Evaluation
runtime owns recommendation generation, so the legacy path must not also emit a
``CRM Action Item`` or a legacy ``CRM Recommendation`` as a generation side
effect. With the flag off -- or set to a value that is not a recognised truthy
token -- the legacy path stays live and unchanged.
"""

import hashlib
import json
import unittest
from unittest.mock import patch

from crm.fcrm.nba import (
	ensure_nba_recommendation,
	nba_evaluation_epoch_active,
	sync_nba_recommendation_for_action,
)

try:
	import frappe
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - pure environment without a bench
	FrappeTestCase = None


class TestEpochFlagTruthTable(unittest.TestCase):
	def test_only_recognised_truthy_tokens_activate_the_epoch(self):
		for value, expected in (
			(1, True),
			("1", True),
			(True, True),
			(0, False),
			("0", False),
			(None, False),
			("true", False),
			("yes", False),
			("maybe", False),
			(2, False),
		):
			conf = {} if value is None else {"crm_nba_evaluation_runtime_enabled": value}
			with patch("crm.fcrm.nba.frappe.conf", conf):
				self.assertIs(nba_evaluation_epoch_active(), expected, msg=repr(value))


if FrappeTestCase is not None:

	class TestNbaEpochExclusion(FrappeTestCase):
		@classmethod
		def setUpClass(cls):
			super().setUpClass()
			cls._conf_backup = {
				key: frappe.conf.get(key)
				for key in (
					"crm_nba_evaluation_runtime_enabled",
					"crm_intelligence_writer_epoch",
					"crm_agents_v2_rollout_epoch",
				)
			}
			frappe.conf.pop("crm_intelligence_writer_epoch", None)
			frappe.conf.pop("crm_agents_v2_rollout_epoch", None)

		@classmethod
		def tearDownClass(cls):
			for key, value in cls._conf_backup.items():
				if value is None:
					frappe.conf.pop(key, None)
				else:
					frappe.conf[key] = value
			super().tearDownClass()

		def setUp(self):
			frappe.set_user("Administrator")
			frappe.conf.pop("crm_nba_evaluation_runtime_enabled", None)
			self._student = self._make_student("_Test Epoch Exclusion Student")

		def tearDown(self):
			frappe.set_user("Administrator")
			frappe.conf.pop("crm_nba_evaluation_runtime_enabled", None)
			frappe.db.delete("CRM Recommendation", {"target_id": self._student.name})
			for name in frappe.db.get_all(
				"CRM Action Item", filters={"student": self._student.name}, pluck="name"
			):
				frappe.delete_doc("CRM Action Item", name, force=True)
			frappe.delete_doc("CRM Lead", self._student.name, force=True)

		def _make_student(self, name):
			phone = "0" + "".join(str((int(c, 16) + 1) % 10) for c in frappe.generate_hash(length=9))
			student = frappe.get_doc({"doctype": "CRM Lead", "student_name": name, "phone": phone})
			previous = getattr(frappe.flags, "student_intake_service", False)
			frappe.flags.student_intake_service = True
			try:
				student.insert(ignore_permissions=True)
			finally:
				frappe.flags.student_intake_service = previous
			return student

		def _generate(self, key):
			"""Drive the real legacy AI generation command for this student."""
			from crm.api import student_decision as api

			revision = int(
				frappe.db.get_value("CRM Lead", self._student.name, "student_context_revision") or 0
			)
			candidate = {
				"context_revision": revision,
				"disposition": "ACT",
				"action_type": "CALL",
				"objective": "Call the family about the offer.",
				"policy_version": "test-v2",
			}
			digest = hashlib.sha256(
				json.dumps(
					candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
				).encode()
			).hexdigest()
			with patch("crm.api.student_decision._require_action_writer"):
				return api.write_canonical_action(
					student=self._student.name,
					expected_context_revision=revision,
					generation_idempotency_key=key,
					producer_identity="crm-agents:v2",
					payload_digest=digest,
					rollout_epoch=0,
					candidate=candidate,
				)

		def _counts(self):
			return (
				frappe.db.count("CRM Action Item", {"student": self._student.name}),
				frappe.db.count("CRM Recommendation", {"target_id": self._student.name}),
			)

		def test_flag_off_runs_the_legacy_generation_path(self):
			with patch("crm.fcrm.nba.ensure_nba_recommendation") as legacy_recommendation:
				legacy_recommendation.return_value = frappe._dict(name=None)
				self._generate("epoch-off-1")
				legacy_recommendation.assert_called_once()
			self.assertEqual(frappe.db.count("CRM Action Item", {"student": self._student.name}), 1)

		def test_flag_on_blocks_action_and_recommendation_side_effects(self):
			frappe.conf["crm_nba_evaluation_runtime_enabled"] = 1
			with patch("crm.fcrm.nba.ensure_nba_recommendation") as legacy_recommendation:
				with self.assertRaises(frappe.ValidationError):
					self._generate("epoch-on-1")
				legacy_recommendation.assert_not_called()
			self.assertEqual(self._counts(), (0, 0))

		def test_flag_on_short_circuits_legacy_recommendation_writers(self):
			frappe.conf["crm_nba_evaluation_runtime_enabled"] = 1
			result = ensure_nba_recommendation(
				student=self._student.name,
				action_type="CALL",
				objective="obj",
				evidence=[],
				priority="medium",
				due_at=None,
				expires_at=None,
			)
			self.assertIsNone(result)
			self.assertIsNone(sync_nba_recommendation_for_action({"recommendation": "does-not-matter"}))
			self.assertEqual(frappe.db.count("CRM Recommendation", {"target_id": self._student.name}), 0)

		def test_malformed_flag_is_treated_as_off(self):
			frappe.conf["crm_nba_evaluation_runtime_enabled"] = "maybe"
			with patch("crm.fcrm.nba.ensure_nba_recommendation") as legacy_recommendation:
				legacy_recommendation.return_value = frappe._dict(name=None)
				self._generate("epoch-malformed-1")
				legacy_recommendation.assert_called_once()
			self.assertEqual(frappe.db.count("CRM Action Item", {"student": self._student.name}), 1)
