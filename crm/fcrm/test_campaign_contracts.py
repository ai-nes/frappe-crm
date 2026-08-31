import pytest

from crm.fcrm.campaign_contracts import (
	canonical_dimension_key,
	forecast_value_kind,
	performance_fact_fingerprint,
	validate_attribution_weights,
	validate_observed_measures,
)


def test_dimension_key_is_stable_and_ignores_null_components():
	assert canonical_dimension_key(
		{"channel": "Search", "campus": "HN", "empty": None}
	) == canonical_dimension_key({"campus": "HN", "channel": "Search"})


def test_dimension_key_rejects_empty_dimensions():
	with pytest.raises(ValueError):
		canonical_dimension_key({"channel": None})


def test_forecast_and_simulation_are_explicitly_distinct():
	assert forecast_value_kind("simulation")["value_kind"] == "simulation"
	with pytest.raises(ValueError):
		forecast_value_kind("actuals")


def test_attribution_weights_must_reconcile_to_one():
	assert validate_attribution_weights([0.25, 0.75])
	assert not validate_attribution_weights([0.25, 0.25])


def test_performance_fact_idempotency_is_source_observation_scoped():
	assert performance_fact_fingerprint(
		source_system="ads", ingestion_run="run-1", source_key="row-1"
	) == performance_fact_fingerprint(source_system="ads", ingestion_run="run-1", source_key="row-1")
	assert performance_fact_fingerprint(
		source_system="ads", ingestion_run="run-1", source_key="row-1"
	) != performance_fact_fingerprint(source_system="ads", ingestion_run="run-2", source_key="row-1")


def test_performance_fact_rejects_negative_observed_measure():
	with pytest.raises(ValueError, match="spend"):
		validate_observed_measures({"spend": -1})
