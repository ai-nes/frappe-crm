"""Frappe-owned presentation of the authoritative CRM score result.

Student 360 may display this projection, but it must not own score thresholds
or derive a second scoring policy. The thresholds below mirror the existing
CRM scoring surface and are kept in this Scoring/Frappe module so every reader
uses one source of truth.
"""
from __future__ import annotations

from typing import Any


SCORE_BAND_THRESHOLDS = (("HIGH", 80.0), ("MEDIUM", 50.0), ("LOW", 0.0))


def score_band(final_score: Any) -> str | None:
	if final_score in (None, ""):
		return None
	try:
		value = float(final_score)
	except (TypeError, ValueError):
		return None
	for band, threshold in SCORE_BAND_THRESHOLDS:
		if value >= threshold:
			return band
	return "LOW"


def score_trend(score_change: Any) -> dict[str, Any]:
	if score_change in (None, ""):
		return {"direction": "UNKNOWN", "delta": None}
	try:
		value = float(score_change)
	except (TypeError, ValueError):
		return {"direction": "UNKNOWN", "delta": None}
	return {"direction": "UP" if value > 0 else "DOWN" if value < 0 else "FLAT", "delta": score_change}
