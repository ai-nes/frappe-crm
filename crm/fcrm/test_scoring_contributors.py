"""Contributor validation contract."""

from unittest import TestCase

import frappe

from crm.fcrm.scoring_contributors import validate_contributors


def _row(**overrides):
	row = {"category": "Fit", "rule_id": "fit_grade_12", "signal": "Grade 12", "score": 20, "reason": ""}
	row.update(overrides)
	return row


class TestScoringContributors(TestCase):
	def test_valid_contributors_are_normalized(self):
		self.assertEqual(validate_contributors([_row(reason="  matched  ")])[0]["reason"], "matched")

	def test_invalid_contributor_shape_is_rejected(self):
		for overrides in (
			{"signal": "contains/untrusted"},
			{"rule_id": ""},
			{"reason": "x" * 241},
			{"category": "Unknown"},
			{"model_version": "v1"},
		):
			with self.subTest(overrides=overrides):
				with self.assertRaises(frappe.ValidationError):
					validate_contributors([_row(**overrides)])

	def test_contributor_row_cap_is_enforced(self):
		with self.assertRaises(frappe.ValidationError):
			validate_contributors([_row() for _ in range(61)])
