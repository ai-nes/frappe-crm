import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _doctype(name):
	path = ROOT / "fcrm" / "doctype" / name / f"{name}.json"
	return json.loads(path.read_text(encoding="utf-8"))


def _fieldnames(doctype):
	return {field["fieldname"] for field in doctype["fields"]}


def test_nba_doctypes_match_the_original_contract_exactly():
	expected = {
		"crm_action_definition": [
			"code",
			"description",
			"purpose",
			"default_channel",
			"allowed_actors",
			"requires_approval",
			"auto_execute",
			"enabled",
		],
		"crm_recommendation": [
			"recommendation_id",
			"target_type",
			"target_id",
			"action",
			"purpose",
			"channel",
			"trigger",
			"reason",
			"evidence",
			"priority",
			"confidence",
			"expected_impact",
			"timing_policy",
			"recommended_at",
			"expires_at",
			"owner",
			"lifecycle_status",
			"decision_status",
			"execution_status",
			"model",
			"model_version",
		],
		"crm_timing_policy": [
			"trigger_type",
			"trigger_event",
			"delay_value",
			"delay_unit",
			"allowed_start_time",
			"allowed_end_time",
			"deadline_type",
			"deadline_offset",
			"recurrence_type",
			"recurrence_interval",
			"stop_condition",
			"optimization_enabled",
			"optimization_objective",
		],
		"crm_action_execution": [
			"recommendation",
			"actor",
			"channel",
			"scheduled_at",
			"started_at",
			"completed_at",
			"status",
			"input",
			"output",
			"error",
		],
		"crm_action_outcome": [
			"execution",
			"outcome_type",
			"outcome_value",
			"success",
			"impact_score",
			"captured_by",
			"captured_at",
			"notes",
		],
		"crm_recommendation_feedback": [
			"recommendation",
			"outcome",
			"predicted_probability",
			"actual_result",
			"reward",
			"actual_impact",
			"feedback_source",
			"created_at",
		],
	}
	for directory, field_order in expected.items():
		doctype = _doctype(directory)
		assert doctype["field_order"] == field_order
		assert list(doctype["fields"][index]["fieldname"] for index in range(len(field_order))) == field_order
		assert _fieldnames(doctype) == set(field_order)


def test_name_is_frappe_system_identity():
	assert _doctype("crm_action_definition")["autoname"] == "field:code"
	assert _doctype("crm_recommendation")["autoname"] == "field:recommendation_id"
	assert _doctype("crm_timing_policy")["autoname"] == "hash"
	assert _doctype("crm_action_execution")["autoname"] == "hash"
	assert _doctype("crm_action_outcome")["autoname"] == "hash"
	assert _doctype("crm_recommendation_feedback")["autoname"] == "hash"
