"""Framework-independent contracts for the canonical admissions facts."""

import pytest

from crm.fcrm.admissions_canonical_contracts import (
	canonical_attempt_key,
	canonical_case_key,
	normalize_planning_scope,
	validate_fact_envelope,
	validate_metric_definition,
	validate_offering,
)
from crm.fcrm.territory_geography import select_effective_assignment


def test_case_and_attempt_keys_are_stable_and_not_preference_identity():
	assert canonical_case_key(" ID-1 ", "2026") == "CK-ID-1-2026"
	first = canonical_attempt_key("CK-ID-1-2026", "OFF-1", "source:1")
	second = canonical_attempt_key("CK-ID-1-2026", "OFF-1", "source:1")

	assert first == second
	assert first != canonical_attempt_key("CK-ID-1-2026", "OFF-1", "source:2")


def test_offering_contract_rejects_invalid_interval_and_quota():
	with pytest.raises(ValueError, match="quota"):
		validate_offering(
			{"admission_year": "2026", "campus": "HN", "major": "CS", "admission_method": "exam", "quota": -1}
		)

	with pytest.raises(ValueError, match="effective_until"):
		validate_offering(
			{
				"admission_year": "2026",
				"campus": "HN",
				"major": "CS",
				"admission_method": "exam",
				"quota": 10,
				"effective_from": "2026-08-01",
				"effective_until": "2026-07-31",
			}
		)


def test_planning_scope_has_deterministic_allow_list_key():
	scope = normalize_planning_scope({"campus": "HN", "major": "CS"})

	assert scope["scope_key"] == "campus:HN|major:CS"
	with pytest.raises(ValueError, match="combination"):
		normalize_planning_scope({"campus": "HN", "major": "CS", "territory": "North"})


def test_fact_envelope_requires_source_time_grain_and_revision():
	valid = {
		"period_start": "2026-01-01",
		"period_end": "2026-01-31",
		"timezone": "Asia/Ho_Chi_Minh",
		"source_system": "ads",
		"source_run": "run-1",
		"recorded_at": "2026-02-01T00:00:00+07:00",
		"revision": 1,
		"idempotency_fingerprint": "fp-1",
		"normalized_dimension": "v1:abc",
	}
	assert validate_fact_envelope(valid)["revision"] == 1

	with pytest.raises(ValueError, match="supersedes"):
		validate_fact_envelope({**valid, "revision": 2})


def test_metric_definition_requires_subject_grain_and_stage_version():
	definition = validate_metric_definition(
		{
			"metric_key": "application_submitted",
			"subject_grain": "Application",
			"unit": "count",
			"aggregation": "count",
			"timezone": "Asia/Ho_Chi_Minh",
			"stage_mapping_version": "admissions-application-v1",
		}
	)

	assert definition["subject_grain"] == "Application"
	with pytest.raises(ValueError, match="subject_grain"):
		validate_metric_definition(
			{
				"metric_key": "bad",
				"subject_grain": "Student",
				"unit": "count",
				"aggregation": "count",
				"timezone": "Asia/Ho_Chi_Minh",
				"stage_mapping_version": "v1",
			}
		)


def test_territory_resolution_fails_closed_on_effective_overlap():
	rows = [
		{"territory": "T-1", "status": "Active", "effective_from": "2026-01-01", "effective_until": "2026-12-31"},
		{"territory": "T-2", "status": "Active", "effective_from": "2026-06-01", "effective_until": "2026-09-30"},
	]
	with pytest.raises(ValueError, match="overlapping"):
		select_effective_assignment(rows, "2026-07-01")
