from datetime import datetime

import pytest

from crm.fcrm.nba_timing import TIME_SLOTS, resolve_scheduled_at, slot_bounds


def test_time_slots_have_four_non_overlapping_daily_ranges():
	assert TIME_SLOTS == ("0-6", "6-12", "12-18", "18-24")
	assert slot_bounds("0-6")[0].hour == 0
	assert slot_bounds("6-12")[0].hour == 6
	assert slot_bounds("12-18")[0].hour == 12
	assert slot_bounds("18-24")[0].hour == 18
	assert slot_bounds("18-24")[1].hour == 0


def test_time_slot_is_used_to_resolve_automatic_schedule():
	result = resolve_scheduled_at(
		{"trigger_type": "schedule", "time_slot": "12-18"},
		now=datetime(2026, 9, 3, 10, 0),
	)

	assert result == datetime(2026, 9, 3, 12, 0)


def test_explicit_schedule_cannot_bypass_time_slot():
	with pytest.raises(ValueError, match="allowed time window"):
		resolve_scheduled_at(
			{"trigger_type": "schedule", "time_slot": "18-24"},
			datetime(2026, 9, 3, 17, 59),
			now=datetime(2026, 9, 3, 8, 0),
		)
	with pytest.raises(ValueError, match="allowed time window"):
		resolve_scheduled_at(
			{"trigger_type": "schedule", "time_slot": "18-24"},
			datetime(2026, 9, 4, 0, 0),
			now=datetime(2026, 9, 3, 8, 0),
		)


def test_time_slot_boundaries_are_end_exclusive():
	with pytest.raises(ValueError, match="allowed time window"):
		resolve_scheduled_at(
			{"trigger_type": "schedule", "time_slot": "0-6"},
			datetime(2026, 9, 3, 6, 0),
			now=datetime(2026, 9, 3, 0, 0),
		)

	assert resolve_scheduled_at(
		{"trigger_type": "schedule", "time_slot": "6-12"},
		datetime(2026, 9, 3, 6, 0),
		now=datetime(2026, 9, 3, 0, 0),
	) == datetime(2026, 9, 3, 6, 0)


def test_evening_time_slot_runs_until_midnight():
	assert resolve_scheduled_at(
		{"trigger_type": "schedule", "time_slot": "18-24"},
		datetime(2026, 9, 3, 23, 59, 59),
		now=datetime(2026, 9, 3, 22, 0),
	) == datetime(2026, 9, 3, 23, 59, 59)


def test_time_slot_rejects_conflicting_legacy_bounds():
	with pytest.raises(ValueError, match="time_slot"):
		resolve_scheduled_at(
			{
				"trigger_type": "schedule",
				"time_slot": "6-12",
				"allowed_start_time": "09:00:00",
				"allowed_end_time": "17:00:00",
			},
			now=datetime(2026, 9, 3, 8, 0),
		)


def test_relative_delay_is_applied_when_schedule_is_omitted():
	result = resolve_scheduled_at(
		{"trigger_type": "relative", "delay_value": 2, "delay_unit": "hours"},
		now=datetime(2026, 9, 3, 8, 0),
	)

	assert result == datetime(2026, 9, 3, 10, 0)


def test_automatic_schedule_moves_to_next_allowed_window():
	result = resolve_scheduled_at(
		{
			"trigger_type": "schedule",
			"delay_value": 0,
			"delay_unit": "hours",
			"allowed_start_time": "09:00:00",
			"allowed_end_time": "17:00:00",
		},
		now=datetime(2026, 9, 3, 8, 0),
	)

	assert result == datetime(2026, 9, 3, 9, 0)


def test_explicit_schedule_cannot_bypass_allowed_window():
	with pytest.raises(ValueError, match="allowed time window"):
		resolve_scheduled_at(
			{
				"trigger_type": "schedule",
				"allowed_start_time": "09:00:00",
				"allowed_end_time": "17:00:00",
			},
			datetime(2026, 9, 3, 20, 0),
			now=datetime(2026, 9, 3, 8, 0),
		)


def test_business_day_deadline_is_enforced():
	result = resolve_scheduled_at(
		{
			"trigger_type": "deadline",
			"deadline_type": "business_days",
			"deadline_offset": 1,
			"delay_value": 0,
			"delay_unit": "days",
		},
		now=datetime(2026, 9, 4, 10, 0),
	)

	assert result == datetime(2026, 9, 4, 10, 0)

	with pytest.raises(ValueError, match="exceeds"):
		resolve_scheduled_at(
			{
				"trigger_type": "deadline",
				"deadline_type": "business_days",
				"deadline_offset": 1,
				"delay_value": 0,
				"delay_unit": "days",
			},
			datetime(2026, 9, 7, 10, 1),
			now=datetime(2026, 9, 4, 10, 0),
		)
