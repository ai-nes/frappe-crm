import pytest
from crm.fcrm.recommendation_rule_constraints import (
	condition_metadata,
	evaluate_conditions,
	has_legacy_stage_condition,
	normalize_conditions,
	normalize_stop_conditions,
	validate_rule_settings,
)


def _conditions():
	return {
		"all": [
			{"field": "student.student_stage", "operator": "in", "value": ["New", "Connected"]},
			{"field": "student.latest_score", "operator": "gte", "value": 70},
		],
		"any": [],
	}


def test_normalize_conditions_accepts_object_and_json_string():
	assert normalize_conditions(_conditions()) == _conditions()
	assert normalize_conditions(
		'{"all": [{"field": "student.student_stage", "operator": "equals", "value": "New"}], "any": []}'
	) == {
		"all": [{"field": "student.student_stage", "operator": "equals", "value": "New"}],
		"any": [],
	}


def test_normalize_conditions_rejects_unknown_fields_and_empty_rules():
	with pytest.raises(ValueError, match="not allowed"):
		normalize_conditions(
			{"all": [{"field": "student.secret_field", "operator": "equals", "value": "x"}], "any": []}
		)
	with pytest.raises(ValueError, match="at least one condition"):
		normalize_conditions({"all": [], "any": []})


def test_evaluate_conditions_supports_all_any_and_nested_student_context():
	context = {"student": {"student_stage": "Connected", "latest_score": 82}}
	assert evaluate_conditions(_conditions(), context) is True
	assert (
		evaluate_conditions(
			{
				"all": [],
				"any": [
					{"field": "student.student_stage", "operator": "equals", "value": "Lost"},
					{"field": "student.student_stage", "operator": "equals", "value": "Connected"},
				],
			},
			context,
		)
		is True
	)


def test_normalize_stop_conditions_rejects_duplicates_and_unknown_codes():
	assert normalize_stop_conditions('["matching_action_completed", "student_lost"]') == [
		"matching_action_completed",
		"student_lost",
	]
	with pytest.raises(ValueError, match="duplicates"):
		normalize_stop_conditions(["student_lost", "student_lost"])
	with pytest.raises(ValueError, match="only contain"):
		normalize_stop_conditions(["unknown"])


def test_condition_metadata_is_safe_for_frontend_pickers():
	fields = condition_metadata()
	assert {field["field"] for field in fields} >= {
		"student.student_stage",
		"student.latest_score",
		"student.owner_staff",
	}
	assert all(field["operators"] for field in fields)
	assert "student.lifecycle_stage" not in {field["field"] for field in fields}


def test_legacy_stage_condition_is_detectable_for_persisted_rules():
	assert has_legacy_stage_condition(
		{"all": [{"field": "student.lifecycle_stage", "operator": "equals", "value": "Lead"}], "any": []}
	)


def test_missing_values_do_not_match_negative_conditions():
	assert (
		evaluate_conditions(
			{
				"all": [{"field": "student.owner_staff", "operator": "not_equals", "value": "staff-1"}],
				"any": [],
			},
			{"student": {}},
		)
		is False
	)


def test_validate_rule_settings_rejects_invalid_values():
	validate_rule_settings("event", "intent.created", "high", 3, "days", 1, 72)
	with pytest.raises(ValueError, match="cooldown cannot be negative"):
		validate_rule_settings("event", "intent.created", "high", -1, "days", 1, None)
