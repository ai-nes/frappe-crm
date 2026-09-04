import pytest

from crm.fcrm.nba_canonical import canonical_digest
from crm.fcrm.nba_policy import (
	decision_policy_digest_payload,
	validate_decision_policy_numbers,
	validate_diversity_rule,
	validate_score_weights,
)

_BASE_ROW = {
	"top_n": 3,
	"max_recommendations": 10,
	"min_score_threshold": 0.0,
	"score_weights": {"recency": 0.4, "intent": 0.6},
	"conflict_key_fields": ["conflict_key"],
	"diversity_rule": "unique_action_type",
}


def test_digest_payload_is_order_independent():
	reordered = {
		"diversity_rule": "unique_action_type",
		"conflict_key_fields": ["conflict_key"],
		"score_weights": {"intent": 0.6, "recency": 0.4},
		"min_score_threshold": 0.0,
		"max_recommendations": 10,
		"top_n": 3,
	}
	assert canonical_digest(decision_policy_digest_payload(_BASE_ROW)) == canonical_digest(
		decision_policy_digest_payload(reordered)
	)


def test_digest_payload_changes_when_a_knob_changes():
	changed = dict(_BASE_ROW, top_n=2)
	assert canonical_digest(decision_policy_digest_payload(_BASE_ROW)) != canonical_digest(
		decision_policy_digest_payload(changed)
	)


def test_digest_payload_normalizes_a_json_string_weight():
	row = dict(_BASE_ROW, score_weights='{"recency": 0.4, "intent": 0.6}')
	assert canonical_digest(decision_policy_digest_payload(row)) == canonical_digest(
		decision_policy_digest_payload(_BASE_ROW)
	)


def test_numeric_validation_accepts_the_conservative_default():
	validate_decision_policy_numbers(3, 10, 0.0)


def test_numeric_validation_rejects_top_n_over_max():
	with pytest.raises(ValueError):
		validate_decision_policy_numbers(11, 10, 0.0)


def test_diversity_rule_validation_rejects_unknown_rule():
	assert validate_diversity_rule("unique_category") == "unique_category"
	with pytest.raises(ValueError):
		validate_diversity_rule("round_robin")


def test_score_weight_validation_rejects_non_numeric_values():
	with pytest.raises(ValueError):
		validate_score_weights({"recency": None})
