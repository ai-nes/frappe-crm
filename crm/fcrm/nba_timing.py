"""Pure scheduling helpers for CRM Timing Policy.

The helpers deliberately do not import Frappe.  This keeps the timing contract
testable in isolation and leaves persistence/permission concerns to the NBA
service layer.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from typing import Any

_UNIT_TO_SECONDS = {
	"minutes": 60,
	"hours": 60 * 60,
	"days": 24 * 60 * 60,
}

TIME_SLOTS = ("0-6", "6-12", "12-18", "18-24")
_TIME_SLOT_HOURS = {
	"0-6": (0, 6),
	"6-12": (6, 12),
	"12-18": (12, 18),
	# 24:00 is represented by the next midnight; selected slots are end-exclusive.
	"18-24": (18, 0),
}


def _number(value: Any, field: str) -> float:
	try:
		result = float(value or 0)
	except (TypeError, ValueError) as exc:
		raise ValueError(f"{field} must be numeric.") from exc
	if result < 0:
		raise ValueError(f"{field} cannot be negative.")
	return result


def _duration(value: Any, unit: Any, field: str) -> timedelta:
	unit_name = str(unit or "hours")
	if unit_name not in _UNIT_TO_SECONDS:
		raise ValueError(f"Unsupported {field} unit: {unit_name}.")
	return timedelta(seconds=_number(value, field) * _UNIT_TO_SECONDS[unit_name])


def _datetime(value: Any, field: str) -> datetime:
	if isinstance(value, datetime):
		return value.replace(tzinfo=None)
	if isinstance(value, date):
		return datetime.combine(value, time.min)
	try:
		return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
	except (TypeError, ValueError) as exc:
		raise ValueError(f"{field} must be a valid datetime.") from exc


def _time(value: Any, field: str) -> time | None:
	if value in (None, ""):
		return None
	if isinstance(value, time):
		return value.replace(tzinfo=None)
	try:
		return time.fromisoformat(str(value).split(".", 1)[0])
	except ValueError as exc:
		raise ValueError(f"{field} must be a valid time.") from exc


def slot_bounds(time_slot: str) -> tuple[time, time]:
	"""Return the concrete daily bounds for a configured time slot."""
	try:
		start_hour, end_hour = _TIME_SLOT_HOURS[time_slot]
	except KeyError as exc:
		raise ValueError(f"Unsupported time_slot: {time_slot}.") from exc
	start = time(hour=start_hour)
	end = time(hour=end_hour)
	return start, end


def slot_for_time(clock: time) -> str:
	"""Return which of the four daily TIME_SLOTS a clock time falls in."""
	for slot in TIME_SLOTS:
		start, end = slot_bounds(slot)
		if _in_window(datetime.combine(date.min, clock), start, end, end_exclusive=True):
			return slot
	raise ValueError(f"Could not resolve a time_slot for {clock}.")


def is_time_allowed(candidate: Any, allowed_slots: Any, *, field: str = "allowed_time_slots") -> bool:
	"""Return whether a datetime/time falls within a set of allowed TIME_SLOTS.

	An empty/falsy ``allowed_slots`` means no restriction is configured.
	"""
	if not allowed_slots:
		return True
	if isinstance(allowed_slots, str):
		try:
			allowed_slots = json.loads(allowed_slots) if allowed_slots else []
		except (TypeError, ValueError) as exc:
			raise ValueError(f"{field} must be a JSON array.") from exc
	if not allowed_slots:
		return True
	invalid = set(allowed_slots) - set(TIME_SLOTS)
	if invalid:
		raise ValueError(f"{field} contains unsupported time slots: {sorted(invalid)}.")
	clock = candidate if isinstance(candidate, time) else _datetime(candidate, "candidate").time()
	return slot_for_time(clock) in set(allowed_slots)


def _add_business_days(start: datetime, days: float) -> datetime:
	whole_days = int(days)
	if days != whole_days:
		raise ValueError("business_days deadline_offset must be a whole number.")
	result = start
	while whole_days:
		result += timedelta(days=1)
		if result.weekday() < 5:
			whole_days -= 1
	return result


def _window_bounds(policy: Mapping[str, Any]) -> tuple[time | None, time | None]:
	start = _time(policy.get("allowed_start_time"), "allowed_start_time")
	end = _time(policy.get("allowed_end_time"), "allowed_end_time")
	if bool(start) != bool(end):
		raise ValueError("allowed_start_time and allowed_end_time must be provided together.")
	time_slot = policy.get("time_slot")
	if time_slot:
		slot_start, slot_end = slot_bounds(str(time_slot))
		if start and end:
			end_matches = end == slot_end
			if start != slot_start or not end_matches:
				raise ValueError("time_slot must match allowed_start_time and allowed_end_time.")
		return slot_start, slot_end
	return start, end


def _in_window(candidate: datetime, start: time, end: time, *, end_exclusive: bool = False) -> bool:
	clock = candidate.time()
	if start <= end:
		return start <= clock < end if end_exclusive else start <= clock <= end
	return clock >= start or (clock < end if end_exclusive else clock <= end)


def _next_window_start(
	candidate: datetime, start: time, end: time, *, end_exclusive: bool = False
) -> datetime:
	if _in_window(candidate, start, end, end_exclusive=end_exclusive):
		return candidate
	result_date = candidate.date()
	if start <= end and candidate.time() > end:
		result_date += timedelta(days=1)
	elif start > end and candidate.time() > end and candidate.time() < start:
		result_date = candidate.date()
	return datetime.combine(result_date, start)


def _deadline(anchor: datetime, policy: Mapping[str, Any]) -> datetime | None:
	deadline_type = str(policy.get("deadline_type") or "none")
	if deadline_type == "none":
		return None
	if deadline_type == "fixed_offset":
		return anchor + _duration(policy.get("deadline_offset"), policy.get("delay_unit"), "deadline_offset")
	if deadline_type == "business_days":
		return _add_business_days(anchor, _number(policy.get("deadline_offset"), "deadline_offset"))
	raise ValueError(f"Unsupported deadline_type: {deadline_type}.")


def resolve_scheduled_at(
	policy: Mapping[str, Any], requested_at: Any = None, *, now: Any = None
) -> datetime:
	"""Resolve and validate one execution time against a CRM Timing Policy.

	An explicit time is never silently moved.  When no time is supplied, the
	policy's delay and next allowed window are used to calculate one.
"""
	anchor = _datetime(now, "now") if now is not None else datetime.now().replace(microsecond=0)
	trigger_type = str(policy.get("trigger_type") or "relative")
	if trigger_type == "event" and not policy.get("trigger_event"):
		raise ValueError("Event timing policies require trigger_event.")

	delay = _duration(policy.get("delay_value"), policy.get("delay_unit"), "delay_value")
	earliest = anchor + delay
	explicit = requested_at is not None
	candidate = _datetime(requested_at, "scheduled_at") if explicit else earliest
	if candidate < earliest:
		raise ValueError("scheduled_at violates the NBA timing delay.")

	start, end = _window_bounds(policy)
	end_exclusive = bool(policy.get("time_slot"))
	if start and end and not _in_window(candidate, start, end, end_exclusive=end_exclusive):
		if explicit:
			raise ValueError("scheduled_at is outside the NBA allowed time window.")
		candidate = _next_window_start(candidate, start, end, end_exclusive=end_exclusive)
		if candidate < earliest:
			candidate += timedelta(days=1)

	deadline = _deadline(anchor, policy)
	if deadline and candidate > deadline:
		raise ValueError("scheduled_at exceeds the NBA timing deadline.")
	return candidate
