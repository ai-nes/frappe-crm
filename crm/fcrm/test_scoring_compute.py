"""Focused unit coverage for the Frappe-owned total and recency semantics."""

from datetime import datetime
from math import isclose
from unittest import TestCase
from unittest.mock import patch

from crm.fcrm.scoring_compute import (
	compute_time_decay,
	compute_total,
	days_since_student_touchpoint,
)


class TestScoringCompute(TestCase):
	def test_compute_total_preserves_raw_weights_and_negative_clamp(self):
		self.assertTrue(isclose(compute_total(50, 30, 60, -10, 0.4, 0.3, 0.3, 1.0), 37.0))
		self.assertTrue(isclose(compute_total(100, 100, 100, -130, 0.4, 0.3, 0.3, 1.0), 0.0))

	def test_positive_components_are_bounded(self):
		for field in ("fit", "engagement", "intent"):
			values = {"fit": 10, "engagement": 10, "intent": 10, "negative": 0}
			values[field] = 101
			with self.subTest(field=field):
				with self.assertRaises(ValueError):
					compute_total(
						values["fit"],
						values["engagement"],
						values["intent"],
						values["negative"],
						0.4,
						0.3,
						0.3,
						1.0,
					)

	def test_negative_component_has_no_minus_100_floor(self):
		self.assertEqual(compute_total(100, 100, 100, -130, 0.4, 0.3, 0.3, 1.0), 0.0)

	def test_time_decay_tier_boundaries_and_uncapped_days(self):
		config = [
			{"max_days": 30, "multiplier": 1.0},
			{"max_days": 60, "multiplier": 0.7},
			{"max_days": 0, "multiplier": 0.2},
		]
		self.assertEqual(compute_time_decay(30, config), 1.0)
		self.assertEqual(compute_time_decay(31, config), 0.7)
		self.assertEqual(compute_time_decay(61, config), 0.2)

	def test_days_since_student_touchpoint_uses_site_local_naive_difference(self):
		with patch(
			"crm.fcrm.scoring_compute.frappe.db.sql",
			return_value=[{"latest": datetime(2026, 6, 1, 12, 0, 0)}],
		) as query:
			result = days_since_student_touchpoint("STU-1", datetime(2026, 6, 12, 12, 0, 0))

		self.assertEqual(result, 11)
		self.assertNotIn("FOR UPDATE", query.call_args.args[0])

	def test_days_since_student_touchpoint_returns_9999_without_qualifying_rows(self):
		with patch("crm.fcrm.scoring_compute.frappe.db.sql", return_value=[{"latest": None}]):
			self.assertEqual(days_since_student_touchpoint("STU-1", datetime(2026, 6, 12)), 9999)
