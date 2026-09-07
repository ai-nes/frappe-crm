"""Framework-independent contract tests for the admissions ERD foundation."""

import pytest

from crm.fcrm.admissions_contracts import (
	ContractValidationError,
	empty_projection,
	lifecycle_reporting_dimension,
	normalize_filters,
)
from crm.fcrm.admissions_migration import migration_summary, profile_rows, provenance


def test_lost_is_a_terminal_dashboard_dimension_with_reason_and_evidence():
	result = lifecycle_reporting_dimension("Lost", "Budget", {"source": "lifecycle-event-1"})

	assert result["dashboard_stage"] == "lost"
	assert result["is_terminal"] is True
	assert result["lost_reason"] == "Budget"
	assert result["evidence"] == {"source": "lifecycle-event-1"}


def test_unknown_lifecycle_value_is_not_silently_coerced():
	assert lifecycle_reporting_dimension("Future stage")["dashboard_stage"] == "unmapped"


def test_filter_contract_normalizes_aliases_and_rejects_unknown_values():
	assert normalize_filters({"from": "2026-01-01", "to": "2026-01-31", "campus": ["HCM", "HCM"]}) == {
		"from_date": "2026-01-01",
		"to_date": "2026-01-31",
		"campus": ["HCM"],
		"granularity": "day",
	}
	with pytest.raises(ContractValidationError):
		normalize_filters({"student_name": "PII"})


def test_filter_contract_preserves_canonical_scope_and_metric_filters():
	assert normalize_filters(
		{
			"planning_scope": "SCOPE-1",
			"metric_key": "applications",
			"source_system": "ads",
			"subject_grain": "Application",
			"status": "Active",
		}
	) == {
		"planning_scope": "SCOPE-1",
		"metric_key": "applications",
		"source_system": "ads",
		"subject_grain": "Application",
		"status": "Active",
		"granularity": "day",
	}


def test_empty_projection_has_stable_contract_and_source_marker():
	result = empty_projection("AdmissionsOverview")

	assert result["contract"] == "admissions-erd-v1"
	assert result["source"]["status"] == "no_data"


def test_migration_helpers_are_deterministic_and_redact_values():
	assert provenance(source_doctype="CRM Lead", source_name="STU-1") == provenance(
		source_doctype="CRM Lead", source_name="STU-1"
	)
	profile = profile_rows([{"major": "CS"}, {"major": "CS"}, {"major": None}], ["major"])
	assert profile["row_count"] == 3
	assert profile["null_counts"] == {"major": 1}
	assert profile["duplicate_counts"] == {"major": 1}
	assert migration_summary(["migrated", "review", "review"]) == {
		"existing": 0,
		"invalid": 0,
		"migrated": 1,
		"review": 2,
		"skipped": 0,
	}
