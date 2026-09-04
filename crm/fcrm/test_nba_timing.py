from datetime import datetime

import pytest

from crm.fcrm.nba_timing import feasible_timing_domain, resolve_scheduled_at


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


def test_feasible_domain_applies_relative_delay_and_cooldown():
	domain = feasible_timing_domain(
		{"trigger_type": "relative", "delay_value": 2, "delay_unit": "hours"},
		now=datetime(2026, 9, 4, 8, 0),
	)

	assert domain["earliest"] == "2026-09-04T10:00:00"
	assert domain["cooldown_seconds"] == 7200
	assert domain["deadline"] is None
	assert domain["recurrence"] == {"type": "none", "interval": 1}


def test_feasible_domain_computes_business_day_deadline():
	domain = feasible_timing_domain(
		{
			"trigger_type": "deadline",
			"deadline_type": "business_days",
			"deadline_offset": 1,
			"delay_value": 0,
			"delay_unit": "days",
		},
		now=datetime(2026, 9, 4, 10, 0),
	)

	assert domain["deadline"] == "2026-09-07T10:00:00"
	assert domain["cooldown_seconds"] == 0


def test_feasible_domain_passes_window_bounds_as_strings():
	domain = feasible_timing_domain(
		{
			"trigger_type": "schedule",
			"allowed_start_time": "09:00:00",
			"allowed_end_time": "17:00:00",
		},
		now=datetime(2026, 9, 4, 8, 0),
	)

	assert domain["window_start"] == "09:00:00"
	assert domain["window_end"] == "17:00:00"
	assert domain["window_wraps_midnight"] is False
	# earliest (now + 0 delay = 08:00) is clamped forward into the window.
	assert domain["earliest"] == "2026-09-04T09:00:00"


def test_feasible_domain_preserves_overnight_window():
	domain = feasible_timing_domain(
		{
			"trigger_type": "schedule",
			"allowed_start_time": "22:00:00",
			"allowed_end_time": "06:00:00",
			"timezone": "Asia/Ho_Chi_Minh",
		},
		now=datetime(2026, 9, 4, 8, 0),
	)

	assert domain["window_start"] == "22:00:00"
	assert domain["window_end"] == "06:00:00"
	assert domain["window_wraps_midnight"] is True
	assert domain["timezone"] == "Asia/Ho_Chi_Minh"


def test_feasible_domain_accepts_timedelta_window_cells():
	from datetime import timedelta

	domain = feasible_timing_domain(
		{
			"trigger_type": "schedule",
			"allowed_start_time": timedelta(hours=9),
			"allowed_end_time": timedelta(hours=17),
		},
		now=datetime(2026, 9, 4, 8, 0),
	)

	assert domain["window_start"] == "09:00:00"
	assert domain["window_end"] == "17:00:00"


def test_feasible_domain_rejects_malformed_unit():
	with pytest.raises(ValueError, match="unit"):
		feasible_timing_domain(
			{"trigger_type": "relative", "delay_value": 1, "delay_unit": "fortnights"},
			now=datetime(2026, 9, 4, 8, 0),
		)
