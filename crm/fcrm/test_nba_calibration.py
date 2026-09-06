import pytest

from crm.fcrm.nba_calibration import (
	build_calibration_report,
	select_attribution_dataset,
	validate_component_weights,
)


WEIGHTS = {"opportunity_fit": 0.45, "urgency": 0.25, "effectiveness_index": 0.30}


def test_dataset_excludes_unlinked_and_non_terminal_rows():
	dataset = select_attribution_dataset(
		[
			{
				"name": "A-1", "evaluation": "E-1", "recommendation": "R-1",
				"action_execution": "X-1", "terminal_result_revision": "APP-3",
				"cohort_key": "2026", "season": "2026", "label": "enrolled",
			},
			{"name": "A-2", "cohort_key": "2026", "season": "2026", "label": "enrolled"},
		],
		cohort_key="2026",
		season="2026",
	)
	assert [row["evaluation"] for row in dataset["rows"]] == ["E-1"]
	assert dataset["exclusions"][0]["row"] == "A-2"


def test_weights_are_exact_finite_simplex():
	assert validate_component_weights(WEIGHTS) == WEIGHTS
	with pytest.raises(ValueError):
		validate_component_weights({"opportunity_fit": 0.5, "urgency": 0.5})
	with pytest.raises(ValueError):
		validate_component_weights({"opportunity_fit": 1.1, "urgency": 0.0, "effectiveness_index": -0.1})


def test_report_digest_is_stable_and_shadow_only():
	dataset = select_attribution_dataset(
		[
			{
				"name": "A-1", "evaluation": "E-1", "recommendation": "R-1",
				"action_execution": "X-1", "terminal_result_revision": "APP-3",
				"cohort_key": "2026", "season": "2026", "label": "enrolled",
				"components": {"opportunity_fit": 0.9, "urgency": 0.2, "effectiveness_index": 0.8},
			}
		],
		cohort_key="2026", season="2026",
	)
	report = build_calibration_report(dataset, [WEIGHTS], baseline=WEIGHTS)
	assert report["promotion"] == {"status": "shadow_only", "approved": False}
	assert len(report["report_digest"]) == 64
