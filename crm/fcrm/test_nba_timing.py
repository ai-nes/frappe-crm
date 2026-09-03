from datetime import datetime

import pytest

from crm.fcrm.nba_timing import resolve_scheduled_at


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
