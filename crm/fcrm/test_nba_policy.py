from datetime import datetime, timedelta

import pytest

from crm.fcrm.nba_canonical import action_definition_snapshot, canonical_digest
from crm.fcrm.nba_policy import (
	eligible_set_digest,
	filter_eligible_actions,
	validate_decision_policy_numbers,
	validate_score_weights,
)

NOW = datetime(2026, 9, 4, 10, 0, 0)


def _row(code="CALL", **overrides):
	row = {
		"code": code,
		"display_name": code.title(),
		"category": "CONTACT",
		"purpose": "reach out",
		"default_channel": "CALL",
		"allowed_actors": ["Sale", "Lead Sales"],
		"requires_approval": 0,
		"auto_execute": 0,
		"enabled": 1,
	}
	row.update(overrides)
	return row


def test_disabled_action_is_excluded():
	result = filter_eligible_actions([_row(enabled=0)], now=NOW)
	assert result["actions"] == []
	assert result["exclusions"] == [{"action": "CALL", "reason": "DISABLED"}]


def test_future_effective_from_is_not_effective():
	result = filter_eligible_actions([_row(effective_from=NOW + timedelta(days=1))], now=NOW)
	assert result["exclusions"] == [{"action": "CALL", "reason": "NOT_EFFECTIVE"}]


def test_past_effective_to_is_expired():
	result = filter_eligible_actions([_row(effective_to=NOW - timedelta(days=1))], now=NOW)
	assert result["exclusions"] == [{"action": "CALL", "reason": "EXPIRED"}]


def test_actor_disjoint_from_allowed_actors_is_rejected():
	result = filter_eligible_actions([_row()], now=NOW, actor_roles={"Marketing"})
	assert result["exclusions"] == [{"action": "CALL", "reason": "ACTOR_NOT_ALLOWED"}]


def test_system_manager_bypasses_the_actor_check():
	result = filter_eligible_actions([_row()], now=NOW, actor_roles={"System Manager"})
	assert [a["code"] for a in result["actions"]] == ["CALL"]


def test_frequency_cap_hit_is_excluded():
	result = filter_eligible_actions(
		[_row()],
		now=NOW,
		recent_action_codes={"CALL": 3},
		cooldown_by_code={"CALL": 3},
	)
	assert result["exclusions"] == [{"action": "CALL", "reason": "FREQUENCY_CAP"}]


def test_frequency_cap_below_threshold_is_allowed():
	result = filter_eligible_actions(
		[_row()],
		now=NOW,
		recent_action_codes={"CALL": 2},
		cooldown_by_code={"CALL": 3},
	)
	assert [a["code"] for a in result["actions"]] == ["CALL"]


def test_unknown_code_is_excluded():
	result = filter_eligible_actions([_row(code="NOT_A_REAL_CODE")], now=NOW)
	assert result["exclusions"] == [{"action": "NOT_A_REAL_CODE", "reason": "UNKNOWN_CODE"}]


def test_happy_path_digest_is_stable_and_order_independent():
	rows = [_row("CALL"), _row("SEND_EMAIL", category="CONTACT")]
	forward = filter_eligible_actions(rows, now=NOW)
	backward = filter_eligible_actions(list(reversed(rows)), now=NOW)
	assert forward == backward
	assert [a["code"] for a in forward["actions"]] == ["CALL", "SEND_EMAIL"]
	assert eligible_set_digest(forward["actions"]) == eligible_set_digest(backward["actions"])


def test_row_digest_is_the_snapshot_digest():
	result = filter_eligible_actions([_row()], now=NOW)
	assert result["actions"][0]["digest"] == canonical_digest(action_definition_snapshot(_row()))


def test_eligible_set_digest_binds_wire_action_ids():
	actions = filter_eligible_actions([_row("CALL")], now=NOW)["actions"]
	expected = canonical_digest(
		[{"action_id": "ACT-CALL", "revision": actions[0]["revision"], "digest": actions[0]["digest"]}]
	)
	assert eligible_set_digest(actions) == expected


def test_validate_decision_policy_numbers_rejects_bad_ranges():
	validate_decision_policy_numbers(3, 10, 0.0)
	with pytest.raises(ValueError):
		validate_decision_policy_numbers(0, 10, 0.0)
	with pytest.raises(ValueError):
		validate_decision_policy_numbers(11, 10, 0.0)
	with pytest.raises(ValueError):
		validate_decision_policy_numbers(3, 51, 0.0)
	with pytest.raises(ValueError):
		validate_decision_policy_numbers(3, 10, 1.5)


def test_validate_score_weights_requires_numeric_object():
	assert validate_score_weights(None) == {}
	assert validate_score_weights('{"a": 0.5}') == {"a": 0.5}
	with pytest.raises(ValueError):
		validate_score_weights({"a": "high"})
	with pytest.raises(ValueError):
		validate_score_weights([1, 2])
