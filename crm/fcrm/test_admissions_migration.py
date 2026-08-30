"""Tests for the read-only migration baseline contract."""

from crm.fcrm.admissions_migration import build_baseline_report, build_batch_report, migration_summary
from crm.fcrm.school_stakeholder_migration import stakeholder_crosswalk_decision


def test_baseline_is_redacted_deterministic_and_never_requests_writes():
	report = build_baseline_report(
		{
			"CRM Major": [
				{"name": "M-1", "major_code": "CS", "major_name": "Computer Science"},
				{"name": "M-2", "major_code": "CS", "major_name": "Computer Science 2"},
			],
		}
	)

	assert report["mode"] == "dry_run"
	assert report["write_count"] == 0
	assert report["profiles"]["CRM Major"]["duplicate_counts"]["major_code"] == 1
	assert "name" not in report["profiles"]["CRM Major"]


def test_batch_report_preserves_order_cursor_and_quarantine_classification():
	report = build_batch_report(
		run_key="run-1",
		phase="campaign_fact_metric",
		cursor="100",
		next_cursor="200",
		outcomes=["migrated", "quarantined"],
	)

	assert report["next_cursor"] == "200"
	assert report["counts"]["quarantined"] == 1
	assert migration_summary(["migrated", "review"]) == {
		"existing": 0,
		"invalid": 0,
		"migrated": 1,
		"review": 1,
		"skipped": 0,
	}


def test_stakeholder_crosswalk_only_maps_one_evidence_backed_person():
	row = {"doctype": "CRM School Contact", "name": "SCHC-1", "contact": "CONT-1"}
	assert stakeholder_crosswalk_decision(row, {"CONT-1": ["PER-1"]})["outcome"] == "migrated"
	assert stakeholder_crosswalk_decision(row, {"CONT-1": ["PER-1", "PER-2"]})["reason"] == "collision"
	assert stakeholder_crosswalk_decision(row, {})["reason"] == "no_person_evidence"
