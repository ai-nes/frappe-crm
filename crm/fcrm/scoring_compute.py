"""Pure scoring calculations owned by Frappe.

The write command is responsible for loading and validating policy data.  This
module only contains the deterministic formula, decay-tier lookup, and the
student-touchpoint recency query so those rules have one server-side owner.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime

import frappe
from frappe.utils import now_datetime

from crm.fcrm.interaction_semantics import DIRECT_TOUCHPOINT_TYPES

_TWO_WAY_TOUCHPOINT_TYPES = frozenset({"CONNECTED", "COUNSELING", "PHONE_CALL", "MEETING"})


def _finite_float(value, *, field: str) -> float:
	try:
		result = float(value)
	except (TypeError, ValueError) as exc:
		raise ValueError(f"{field} must be a finite number") from exc
	if not math.isfinite(result):
		raise ValueError(f"{field} must be a finite number")
	return result


def validate_component_scores(*, fit, engagement, intent, negative) -> dict[str, float]:
	"""Coerce and validate the four component-score contracts.

	Positive scorers are bounded by the visible 0--100 contract.  Negative is a
	penalty aggregate and may be below -100; the total formula clamps the final
	visible score instead.
	"""
	values = {
		"fit": _finite_float(fit, field="fit"),
		"engagement": _finite_float(engagement, field="engagement"),
		"intent": _finite_float(intent, field="intent"),
		"negative": _finite_float(negative, field="negative"),
	}
	for field in ("fit", "engagement", "intent"):
		if not 0.0 <= values[field] <= 100.0:
			raise ValueError(f"{field} must be between 0 and 100")
	if values["negative"] > 0.0:
		raise ValueError("negative must be less than or equal to 0")
	return values


def compute_total(
	fit,
	engagement,
	intent,
	negative,
	fit_weight,
	engagement_weight,
	intent_weight,
	time_decay_factor,
) -> float:
	"""Return the authoritative 0--100 total using raw template weights."""
	components = validate_component_scores(fit=fit, engagement=engagement, intent=intent, negative=negative)
	decay = _finite_float(time_decay_factor, field="time_decay_factor")
	if not 0.0 < decay <= 1.0:
		raise ValueError("time_decay_factor must be greater than 0 and at most 1")
	weights = {
		"fit": _finite_float(fit_weight, field="fit_weight"),
		"engagement": _finite_float(engagement_weight, field="engagement_weight"),
		"intent": _finite_float(intent_weight, field="intent_weight"),
	}
	raw = (
		weights["fit"] * components["fit"]
		+ (weights["engagement"] * components["engagement"] + weights["intent"] * components["intent"])
		* decay
		+ min(0.0, components["negative"])
	)
	if not math.isfinite(raw):
		raise ValueError("computed total must be finite")
	return max(0.0, min(100.0, raw))


def compute_time_decay(days_since: int, time_decay_config: Sequence[Mapping] | None) -> float:
	"""Return the first matching decay tier, preserving the existing semantics."""
	try:
		days = max(0, int(days_since))
	except (TypeError, ValueError) as exc:
		raise ValueError("days_since must be an integer") from exc
	rows = list(time_decay_config or [])
	if not rows:
		return 1.0
	bounded = sorted(
		(row for row in rows if int(row.get("max_days") or 0) > 0),
		key=lambda row: int(row.get("max_days") or 0),
	)
	for row in bounded:
		if days <= int(row.get("max_days") or 0):
			factor = _finite_float(row.get("multiplier", 1.0), field="time_decay_factor")
			if not 0.0 < factor <= 1.0:
				raise ValueError("time_decay_factor must be greater than 0 and at most 1")
			return factor
	catchall = next((row for row in rows if int(row.get("max_days") or 0) == 0), None)
	if catchall is None:
		return 1.0
	factor = _finite_float(catchall.get("multiplier", 0.1), field="time_decay_factor")
	if not 0.0 < factor <= 1.0:
		raise ValueError("time_decay_factor must be greater than 0 and at most 1")
	return factor


def _as_naive_site_datetime(value) -> datetime:
	result = value if isinstance(value, datetime) else frappe.utils.get_datetime(value)
	if result.tzinfo is not None:
		result = result.replace(tzinfo=None)
	return result


def days_since_student_touchpoint(student, now: datetime | None = None) -> int:
	"""Return days since the latest student-evidenced direct touchpoint.

		Inbound direct touchpoints evidence the student.  Outbound call/meeting
		rows count only for the canonical two-way touchpoint types; outbound email,
	message, and outreach rows do not reset the student's recency clock.
	Historical rows with a NULL direction therefore only qualify through that
	two-way type set.  The query intentionally runs before the Student CAS lock.
	"""
	student_name = getattr(student, "name", None) or (
		student.get("name") if isinstance(student, Mapping) else student
	)
	if not student_name:
		return 9999
	current = _as_naive_site_datetime(now or now_datetime())
	direct_types = sorted(DIRECT_TOUCHPOINT_TYPES)
	two_way_types = sorted(_TWO_WAY_TOUCHPOINT_TYPES)
	direct_placeholders = ", ".join(["%s"] * len(direct_types))
	two_way_placeholders = ", ".join(["%s"] * len(two_way_types))
	rows = frappe.db.sql(
		"SELECT MAX(interaction_datetime) AS latest "
		"FROM `tabCRM Interaction` "
		"WHERE student = %s "
		f"AND interaction_type IN ({direct_placeholders}) "
		"AND (direction = 'inbound' "
		f"OR interaction_type IN ({two_way_placeholders})) "
		"AND COALESCE(outcome, '') NOT IN ('No Response', 'Uncontactable', 'Data Error')",
		(student_name, *direct_types, *two_way_types),
		as_dict=True,
	)
	latest = rows[0].get("latest") if rows else None
	if not latest:
		return 9999
	latest = _as_naive_site_datetime(latest)
	return max(0, (current - latest).days)
