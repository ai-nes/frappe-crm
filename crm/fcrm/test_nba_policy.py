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
		"allowed_actors": ["Sale", "Lead Sale"],
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


def test_contact_action_requires_authoritative_consent_and_channel():
	result = filter_eligible_actions(
		[_row()],
		now=NOW,
		decision_context={"student_stage": "Connected", "contactability": {"consent": True, "channels": ["EMAIL"]}},
	)
	assert result["actions"] == []
	assert result["exclusions"] == [{"action": "CALL", "reason": "CHANNEL_NOT_ALLOWED"}]


def test_contact_action_fails_closed_when_recipient_is_ambiguous():
	result = filter_eligible_actions(
		[_row()],
		now=NOW,
		decision_context={
			"student_stage": "Connected",
			"contactability": {
				"consent": True,
				"channels": ["CALL"],
				"recipient_bound": False,
			}
		},
	)
	assert result["actions"] == []
	assert result["exclusions"] == [{"action": "CALL", "reason": "RECIPIENT_AMBIGUOUS"}]


def test_missing_student_stage_fails_closed_even_with_legacy_lifecycle():
	result = filter_eligible_actions(
		[_row()],
		now=NOW,
		decision_context={
			"lifecycle": {"stage": "enrolled"},
			"contactability": {"consent": True, "channels": ["CALL"]},
		},
	)
	assert result["exclusions"] == [{"action": "CALL", "reason": "STUDENT_STAGE_UNKNOWN"}]


def test_terminal_student_stage_blocks_contact_action_before_scoring():
	result = filter_eligible_actions(
		[_row()],
		now=NOW,
		decision_context={
			"student_stage": "Qualified",
			"contactability": {"consent": True, "channels": ["CALL"]},
		},
	)
	assert result["exclusions"] == [{"action": "CALL", "reason": "STUDENT_STAGE_TERMINAL"}]


def test_live_student_stage_ignores_legacy_lifecycle_stage():
	result = filter_eligible_actions(
		[_row()],
		now=NOW,
		decision_context={
			"student_stage": "Connected",
			"lifecycle": {"stage": "enrolled"},
			"contactability": {"consent": True, "channels": ["CALL"]},
		},
	)
	assert [action["code"] for action in result["actions"]] == ["CALL"]


def test_new_student_excludes_application_actions():
	result = filter_eligible_actions(
		[_row("REMIND_APPLICATION", category="APPLICATION")],
		now=NOW,
		decision_context={
			"student_stage": "New",
			"contactability": {"consent": True, "channels": ["CALL"]},
		},
	)
	assert result["exclusions"] == [{"action": "REMIND_APPLICATION", "reason": "STUDENT_STAGE_NOT_ALLOWED"}]


def test_connected_student_allows_application_actions():
	result = filter_eligible_actions(
		[_row("REMIND_APPLICATION", category="APPLICATION")],
		now=NOW,
		decision_context={
			"student_stage": "Connected",
			"contactability": {"consent": True, "channels": ["CALL"]},
		},
	)
	assert [action["code"] for action in result["actions"]] == ["REMIND_APPLICATION"]


def test_unknown_student_stage_fails_closed():
	result = filter_eligible_actions(
		[_row()],
		now=NOW,
		decision_context={
			"student_stage": None,
			"contactability": {"consent": True, "channels": ["CALL"]},
		},
	)
	assert result["exclusions"] == [{"action": "CALL", "reason": "STUDENT_STAGE_UNKNOWN"}]


def test_parent_action_is_deferred_until_recipient_specific_consent_exists():
	row = _row("CONTACT_PARENT", category="PARENT")
	result = filter_eligible_actions(
		[row],
		now=NOW,
		decision_context={"student_stage": "Connected", "contactability": {"consent": True, "channels": ["CALL"]}},
		parent_authority_channels={"CALL"},
	)
	assert result["actions"] == []
	assert result["exclusions"] == [
		{"action": "CONTACT_PARENT", "reason": "PARENT_AUTHORITY_MISSING"}
	]


def test_unknown_code_is_excluded():
	result = filter_eligible_actions([_row(code="NOT_A_REAL_CODE")], now=NOW)
	assert result["exclusions"] == [{"action": "NOT_A_REAL_CODE", "reason": "UNKNOWN_CODE"}]


def test_action_without_explicit_opportunity_mapping_is_excluded():
	result = filter_eligible_actions([_row("REASSIGN_ADVISOR")], now=NOW)
	assert result["actions"] == []
	assert result["exclusions"] == [{"action": "REASSIGN_ADVISOR", "reason": "NO_OPPORTUNITY_MAPPING"}]


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


def test_allowed_time_slots_pass_through_as_a_normalised_list():
	actions = filter_eligible_actions([_row(allowed_time_slots=["6-12", "12-18"])], now=NOW)["actions"]
	assert actions[0]["allowed_time_slots"] == ["6-12", "12-18"]


def test_allowed_time_slots_json_string_is_parsed():
	actions = filter_eligible_actions([_row(allowed_time_slots='["18-24"]')], now=NOW)["actions"]
	assert actions[0]["allowed_time_slots"] == ["18-24"]


def test_missing_allowed_time_slots_is_an_empty_list():
	actions = filter_eligible_actions([_row()], now=NOW)["actions"]
	assert actions[0]["allowed_time_slots"] == []


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
