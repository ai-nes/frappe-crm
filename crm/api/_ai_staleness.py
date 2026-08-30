"""Fail-closed projection helpers for AI-owned fields."""

from __future__ import annotations

from datetime import datetime

import frappe
from frappe.utils import get_datetime, now_datetime

DEFAULT_AI_STALENESS_SECONDS = 86_400


def ai_staleness_threshold_seconds() -> float | None:
	value = frappe.conf.get("crm_ai_staleness_threshold_seconds", DEFAULT_AI_STALENESS_SECONDS)
	if value in (None, "", "infinity", "inf"):
		return float("inf")
	try:
		parsed = float(value)
		return parsed if parsed >= 0 else None
	except (OverflowError, TypeError, ValueError):
		return None


def ai_field_or_unavailable(record: dict, fieldname: str, *, threshold_seconds: float | None = None) -> dict:
	"""Return one AI field or an explicit unavailable sentinel."""
	generated_at = record.get("ai_generated_at")
	if not generated_at:
		return {"ai_available": False, "reason": "missing_generated_at", "generated_at": None}
	try:
		stamp: datetime = get_datetime(generated_at)
	except (OverflowError, TypeError, ValueError):
		return {"ai_available": False, "reason": "invalid_generated_at", "generated_at": None}
	if not stamp:
		return {"ai_available": False, "reason": "invalid_generated_at", "generated_at": None}
	threshold = ai_staleness_threshold_seconds() if threshold_seconds is None else threshold_seconds
	if threshold is None:
		return {"ai_available": False, "reason": "invalid_staleness_threshold", "generated_at": str(generated_at)}
	if (now_datetime() - stamp).total_seconds() > threshold:
		return {"ai_available": False, "reason": "stale", "generated_at": str(generated_at)}
	value = record.get(fieldname)
	if value is None or (isinstance(value, str) and not value.strip()):
		return {"ai_available": False, "reason": "missing_value", "generated_at": str(generated_at)}
	return {"ai_available": True, "value": value, "generated_at": str(generated_at)}


__all__ = ["ai_field_or_unavailable", "ai_staleness_threshold_seconds"]
