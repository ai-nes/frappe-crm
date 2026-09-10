"""``settle_analysis_stage`` accepts an optional result digest.

The parameter is additive and nullable: callers that omit it settle exactly as
before. Validation of the 64-hex shape is pure and tested here; persistence and
fenced settlement are covered by the Bench suite.
"""

import unittest
from unittest.mock import patch

import frappe

from crm.api import intelligence_runs as api
from crm.fcrm import intelligence_runs


class TestResultDigestValidation(unittest.TestCase):
	def test_accepts_lowercase_64_hex(self):
		digest = "a" * 64
		self.assertEqual(intelligence_runs._validated_result_digest(digest), digest)

	def test_uppercase_is_normalized(self):
		self.assertEqual(intelligence_runs._validated_result_digest("A" * 64), "a" * 64)

	def test_none_and_empty_pass_through(self):
		self.assertIsNone(intelligence_runs._validated_result_digest(None))
		self.assertIsNone(intelligence_runs._validated_result_digest(""))

	def test_rejects_wrong_length_or_alphabet(self):
		for bad in ("a" * 63, "a" * 65, "g" * 64, "z9" * 32):
			with self.assertRaises(frappe.ValidationError):
				intelligence_runs._validated_result_digest(bad)


class TestSettleAnalysisStageForwarding(unittest.TestCase):
	def test_result_digest_is_forwarded_to_the_authority(self):
		with patch("crm.fcrm.intelligence_runs.settle_stage", return_value={"status": "completed"}) as settle:
			api.settle_analysis_stage(
				run_type="CRM Student Analysis Run",
				run_id="RUN-1",
				stage_kind="student_360",
				stage_generation=1,
				lease_token="tok",
				expected_source_revision="4",
				expected_source_digest="d" * 64,
				status="completed",
				result_digest="b" * 64,
			)
		self.assertEqual(settle.call_args.kwargs["result_digest"], "b" * 64)

	def test_existing_callers_without_digest_are_unaffected(self):
		with patch("crm.fcrm.intelligence_runs.settle_stage", return_value={"status": "abstained"}) as settle:
			api.settle_analysis_stage(
				run_type="CRM Student Analysis Run",
				run_id="RUN-1",
				stage_kind="student_360",
				stage_generation=1,
				lease_token="tok",
				expected_source_revision="4",
				expected_source_digest="d" * 64,
				status="abstained",
			)
		self.assertIsNone(settle.call_args.kwargs["result_digest"])
