"""Schema contracts for the admissions ERD foundation."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]


def _meta(doctype: str) -> dict:
	path = ROOT / "crm" / "fcrm" / "doctype" / doctype / f"{doctype}.json"
	return json.loads(path.read_text(encoding="utf-8"))


def _fields(meta: dict) -> dict:
	return {field["fieldname"]: field for field in meta["fields"]}


def test_phase1_master_data_fields_are_additive_and_canonical():
	high_school = _fields(_meta("crm_high_school"))
	campus = _fields(_meta("crm_campus"))
	major = _fields(_meta("crm_major"))
	campaign = _fields(_meta("crm_campaign"))

	assert {"school_tier", "boarding_type", "latitude", "longitude"} <= set(high_school)
	assert high_school["latitude"]["fieldtype"] == "Float"
	assert high_school["longitude"]["fieldtype"] == "Float"
	assert {"city", "latitude", "longitude", "current_enrolled", "target_enrolled", "highlight_major"} <= set(
		campus
	)
	assert major["degree_name"]["fieldtype"] == "Data"
	assert campaign["stable_code"]["fieldtype"] == "Data"
	assert campaign["channel_boundary"]["options"].splitlines()[1:] == [
		"Digital",
		"Field",
		"Partner",
		"Mixed",
	]


def test_phase1_facts_have_period_and_idempotency_keys():
	for doctype, expected in {
		"crm_territory": {"parent_territory", "effective_from", "effective_until"},
		"crm_staff_capacity_period": {"staff", "period_start", "period_end", "capacity_units"},
		"crm_target": {
			"admission_year",
			"metric_key",
			"planning_scope",
			"version",
			"idempotency_fingerprint",
		},
		"crm_geography_market_snapshot": {"geography_type", "geography", "coverage", "confidence", "source"},
	}.items():
		assert expected <= set(_fields(_meta(doctype)))

	target = _meta("crm_target")
	assert any(
		index["fields"][:4] == ["admission_year", "period_start", "period_end", "metric_key"]
		for index in target["indexes"]
	)


def test_canonical_admission_and_dashboard_facts_have_declared_grain():
	application = _fields(_meta("crm_admission_application"))
	assert {"case_key", "offering", "application_attempt_key"} <= set(application)
	assert application["application_attempt_key"]["unique"] == 1
	assert application["case_key"]["reqd"] == 1
	assert application["offering"]["reqd"] == 1

	for doctype, grain, unique_fields in (
		(
			"crm_admission_offering",
			{"admission_year", "campus", "major", "admission_method", "quota", "policy_version"},
			{"admission_year", "campus", "major", "admission_method", "policy_version", "effective_from"},
		),
		(
			"crm_planning_scope",
			{"scope_key", "campus", "major", "effective_from", "effective_until"},
			{"scope_key"},
		),
		(
			"crm_metric_definition",
			{"metric_key", "subject_grain", "timezone", "stage_mapping_version"},
			{"metric_key"},
		),
		(
			"crm_territory_geography_assignment",
			{"territory", "geography_type", "geography", "effective_from", "effective_until", "revision"},
			{"territory", "geography_type", "geography", "effective_from", "revision"},
		),
		(
			"crm_campaign_performance_fact",
			{
				"campaign",
				"channel_assignment",
				"normalized_dimension",
				"period_start",
				"period_end",
				"timezone",
				"source_system",
				"ingestion_run",
				"revision",
				"supersedes",
			},
			{
				"campaign",
				"channel_assignment",
				"period_start",
				"period_end",
				"timezone",
				"normalized_dimension",
				"revision",
			},
		),
	):
		meta = _meta(doctype)
		fields = _fields(meta)
		assert grain <= set(fields)
		has_index = any(
			set(index["fields"]) == unique_fields and index["unique"] for index in meta["indexes"]
		)
		has_unique_field = len(unique_fields) == 1 and fields[next(iter(unique_fields))].get("unique") == 1
		assert has_index or has_unique_field


def test_target_lead_and_student_boundaries_are_explicit():
	lead = _fields(_meta("crm_lead"))
	student = _fields(_meta("crm_student"))

	assert {
		"lead_code",
		"processing_status",
		"resolution",
		"conversion_blockers",
		"converted_student",
		"id_number",
		"high_school",
		"major",
	} <= set(lead)
	assert {"source_lead", "converted_at", "id_number", "high_school", "major"} <= set(student)


def test_core_child_records_expose_canonical_student_links():
	for doctype in (
		"crm_interaction",
		"crm_interaction_evidence",
		"crm_intent",
		"crm_score_history",
		"crm_student_analysis_run",
		"crm_student_assessment",
		"crm_nba_evaluation",
		"task",
		"crm_action_item",
		"crm_admission_application",
	):
		assert "crm_student" in _fields(_meta(doctype)), doctype


def test_high_school_snapshot_preserves_legacy_ne_fields_and_adds_fact_metrics():
	fields = _fields(_meta("crm_high_school_annual_snapshot"))
	assert {"ne_target", "ne_actual", "ne_actual_semantics"} <= set(fields)
	assert {
		"measured_on",
		"period_type",
		"average_score",
		"conversion_rate",
		"enrollment_rate",
		"forecast_count",
		"idempotency_fingerprint",
	} <= set(fields)
