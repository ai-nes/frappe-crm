import pytest

from crm.fcrm.admissions_reconciliation import build_reconciliation_report, reader_rollout_state, reconcile_cohort


def test_reconciliation_blocks_unexplained_kpi_delta():
	result = reconcile_cohort({"application_count": 10}, {"application_count": 11})

	assert result["status"] == "blocked"
	assert result["blockers"] == ["application_count"]


def test_reconciliation_accepts_declared_currency_tolerance():
	result = build_reconciliation_report([{
		"key": "2026/HN/CS",
		"legacy": {"spend": 100.00},
		"target": {"spend": 100.005},
		"tolerances": {"spend": 0.01},
	}])

	assert result["status"] == "parity"


def test_rollback_is_reader_only_and_keeps_target_facts():
	state = reader_rollout_state("legacy")

	assert state["reader"] == "legacy_projection"
	assert state["physical_delete"] is False
	with pytest.raises(ValueError):
		reader_rollout_state("delete")
