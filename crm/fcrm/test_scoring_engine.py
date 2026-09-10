"""Rule scorer specs ported from the retired crm-agents implementation."""

from datetime import datetime, timedelta
from unittest import TestCase

from crm.fcrm.scoring_engine import (
	calculate_engagement_score,
	calculate_fit_score,
	calculate_intent_score,
	calculate_negative_score,
)
from crm.fcrm.scoring_run import _bounded_contributors, _scoring_since_date

_REF = datetime(2026, 6, 12, 7, 0, 0)


def _property_rule(key, field, operator, value, points=20):
	return {
		"signal_key": key,
		"signal_label": key,
		"signal_type": "property",
		"category": "Fit",
		"is_active": True,
		"base_points": points,
		"condition_field": field,
		"condition_operator": operator,
		"condition_value": value,
	}


def _interaction(key, days_ago):
	return {
		"interaction_semantic_key": key,
		"interaction_datetime": (_REF - timedelta(days=days_ago)).isoformat(),
	}


class TestScoringEngine(TestCase):
	def test_rule_inputs_keep_the_legacy_180_day_window(self):
		self.assertEqual(_scoring_since_date(_REF), "2025-12-14")

	def test_repeated_contributors_are_collapsed_and_bounded(self):
		details = [
			{
				"category": "Engagement",
				"rule_id": f"rule_{index}",
				"signal": f"rule_{index}",
				"score": 1,
				"reason": "",
			}
			for index in range(61)
		]
		bounded = _bounded_contributors(details)
		self.assertEqual(len(bounded), 60)
		self.assertEqual(sum(row["score"] for row in bounded), 61)

	def test_fit_uses_student_and_child_table_signal_context(self):
		result = calculate_fit_score(
			{"major": "CNTT"},
			[{"school_year": "2025-2026", "grade": "12", "gpa": 8.5}],
			[],
			[_property_rule("grade12", "grade", "=", "12"), _property_rule("major", "major", "!=", "")],
		)
		self.assertEqual(result.score, 40)
		self.assertEqual({row["rule_id"] for row in result.details}, {"grade12", "major"})

	def test_fit_supports_contains_and_in_operators(self):
		result = calculate_fit_score(
			{"major": "Computer Science", "campus": "HCMC"},
			[],
			[],
			[
				_property_rule("major_contains", "major", "contains", "science", points=10),
				_property_rule("campus_in", "campus", "in", "HN,HCMC", points=15),
			],
		)
		self.assertEqual(result.score, 25)

	def test_engagement_caps_each_rule_before_global_cap(self):
		rule = {
			"signal_key": "open_day",
			"signal_label": "Open Day",
			"signal_type": "interaction",
			"interaction_semantic_key": "OPEN_DAY",
			"base_points": 30,
			"max_points": 50,
			"is_active": True,
		}
		result = calculate_engagement_score([_interaction("OPEN_DAY", 1)] * 3, [rule])
		self.assertEqual(result.score, 50)
		self.assertEqual(len(result.details), 1)

	def test_intent_negative_polarity_cannot_make_an_negative_intent_component(self):
		intent = {
			"name": "INT-1",
			"intent_type": "TUITION",
			"intent_semantic_key": "TUITION",
			"intent_role": "Dominant",
			"polarity": "Negative",
			"importance": "High",
			"confidence": 100,
			"interaction_date": _REF.isoformat(),
		}
		rule = {
			"signal_key": "intent_tuition",
			"signal_type": "intent",
			"intent_semantic_key": "TUITION",
			"base_points": 60,
			"is_active": True,
		}
		result = calculate_intent_score([intent], [rule], _REF, [])
		self.assertEqual(result.score, 0)
		self.assertEqual(result.details[0]["score"], -60)

	def test_negative_inactivity_is_highest_matching_tier_only(self):
		rules = [
			{
				"signal_key": "inactive_30",
				"signal_label": "Inactive 30d",
				"signal_type": "inactivity",
				"inactivity_days": 30,
				"penalty_amount": 10,
			},
			{
				"signal_key": "inactive_90",
				"signal_label": "Inactive 90d",
				"signal_type": "inactivity",
				"inactivity_days": 90,
				"penalty_amount": 40,
			},
		]
		result = calculate_negative_score([_interaction("OPEN_DAY", 95)], rules, _REF)
		self.assertEqual(result.score, -40)
		self.assertEqual(len(result.details), 1)

	def test_negative_ignores_inactive_rules(self):
		rules = [
			{
				"signal_key": "inactive_penalty",
				"signal_label": "Inactive penalty",
				"signal_type": "interaction",
				"interaction_semantic_key": "OPEN_DAY",
				"penalty_amount": 25,
				"is_active": False,
			},
			{
				"signal_key": "inactive_tier",
				"signal_label": "Inactive tier",
				"signal_type": "inactivity",
				"inactivity_days": 30,
				"penalty_amount": 20,
				"is_active": False,
			},
		]
		result = calculate_negative_score([_interaction("OPEN_DAY", 95)], rules, _REF)
		self.assertEqual(result.score, 0)
		self.assertEqual(result.details, [])
