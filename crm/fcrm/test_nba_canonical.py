from datetime import time, timedelta

import pytest

from crm.fcrm.nba_canonical import (
	action_definition_snapshot,
	canonical_digest,
	json_string_list,
	time_text,
	timing_policy_snapshot,
)
from crm.fcrm.test_nba_evaluation_contract import canonical_digest as contract_canonical_digest


@pytest.mark.parametrize(
	"value",
	[
		{"b": 1, "a": 2},
		{"a": 2, "b": 1},
		[1, 2, 3],
		"plain string",
		{"nested": {"z": [3, 2, 1], "y": "tôi"}},
		None,
		42,
	],
)
def test_canonical_digest_matches_the_contract_helper(value):
	assert canonical_digest(value) == contract_canonical_digest(value)


def test_canonical_digest_is_insensitive_to_key_order():
	assert canonical_digest({"a": 1, "b": {"c": 2, "d": 3}}) == canonical_digest(
		{"b": {"d": 3, "c": 2}, "a": 1}
	)


def test_canonical_digest_rejects_non_json_values():
	with pytest.raises(TypeError):
		canonical_digest(object())


def test_action_definition_snapshot_is_deterministic_and_order_independent():
	row_a = {
		"code": "CALL",
		"display_name": "Gọi điện",
		"category": "CONTACT",
		"purpose": "Reach the family",
		"default_channel": "CALL",
		"allowed_actors": ["Lead Sales", "Sale"],
		"requires_approval": 0,
		"auto_execute": 1,
		"enabled": 1,
	}
	row_b = {
		"enabled": True,
		"auto_execute": "1",
		"requires_approval": False,
		"allowed_actors": ["Sale", "Lead Sales", "Sale"],
		"default_channel": "CALL",
		"purpose": "Reach the family",
		"action_type": "CONTACT",
		"display_name": "Gọi điện",
		"code": "CALL",
	}
	snap_a = action_definition_snapshot(row_a)
	assert snap_a["allowed_actors"] == ["Lead Sales", "Sale"]
	assert canonical_digest(snap_a) == canonical_digest(action_definition_snapshot(row_b))


def test_action_definition_snapshot_parses_json_actor_string():
	snap = action_definition_snapshot({"code": "CALL", "allowed_actors": '["Sale", "Lead Sales"]'})
	assert snap["allowed_actors"] == ["Lead Sales", "Sale"]


def test_time_text_normalises_timedelta_and_short_strings():
	assert time_text(timedelta(hours=9)) == "09:00:00"
	assert time_text(timedelta(hours=17, minutes=30)) == "17:30:00"
	assert time_text(time(9, 5)) == "09:05:00"
	assert time_text("9:00:00") == "09:00:00"
	assert time_text(None) is None


def test_json_string_list_coerces_and_rejects_non_lists():
	assert json_string_list('["b", "a", "a"]') == ["a", "b"]
	assert json_string_list("a, b") == ["a", "b"]
	assert json_string_list(None) == []
	with pytest.raises(ValueError):
		json_string_list(42)


def test_timing_policy_snapshot_normalises_timedelta_window():
	snap = timing_policy_snapshot(
		{"code": "X", "allowed_start_time": timedelta(hours=9), "allowed_end_time": timedelta(hours=17)}
	)
	assert snap["allowed_start_time"] == "09:00:00"
	assert snap["allowed_end_time"] == "17:00:00"


def test_timing_policy_snapshot_stringifies_times_and_is_stable():
	row = {
		"trigger_type": "relative",
		"delay_value": 2,
		"delay_unit": "hours",
		"allowed_start_time": "09:00:00",
		"allowed_end_time": "17:00:00",
		"deadline_type": "none",
		"deadline_offset": 0,
		"recurrence_type": "none",
		"recurrence_interval": 1,
	}
	snap = timing_policy_snapshot(row)
	assert snap["allowed_start_time"] == "09:00:00"
	assert canonical_digest(snap) == canonical_digest(timing_policy_snapshot(dict(row)))
