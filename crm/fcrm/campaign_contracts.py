"""Pure helpers for canonical campaign facts and forecast lineage."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_dimension_key(values: dict[str, Any]) -> str:
	"""Return a stable hash for a non-null reporting dimension set."""

	if not isinstance(values, dict):
		raise ValueError("dimension values must be an object")
	cleaned = {
		str(key): str(value).strip()
		for key, value in values.items()
		if value not in (None, "") and str(value).strip()
	}
	if not cleaned:
		raise ValueError("at least one dimension is required")
	payload = json.dumps(cleaned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
	return f"v1:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def forecast_value_kind(value_kind: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
	"""Keep actual, forecast, and simulation values separate at the boundary."""

	if value_kind not in {"actual", "forecast", "simulation"}:
		raise ValueError("value_kind must be actual, forecast, or simulation")
	return {"value_kind": value_kind, "lineage": source or {}}


def validate_attribution_weights(weights: list[float], tolerance: float = 0.0001) -> bool:
	"""Validate a multi-touch allocation without rounding away the contract."""

	if not weights or any(weight < 0 for weight in weights):
		return False
	return abs(sum(weights) - 1.0) <= tolerance


def performance_fact_fingerprint(*, source_system: str, ingestion_run: str, source_key: str) -> str:
	"""Return the stable idempotency key for one source observation."""

	values = (
		str(source_system or "").strip(),
		str(ingestion_run or "").strip(),
		str(source_key or "").strip(),
	)
	if not all(values):
		raise ValueError("source_system, ingestion_run and source_key are required")
	return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


def validate_observed_measures(values: dict[str, Any]) -> dict[str, float]:
	"""Reject negative raw measures before they reach the atomic fact writer."""

	allowed = ("spend", "impressions", "clicks", "leads", "applications", "enrolled")
	result = {}
	for fieldname in allowed:
		try:
			value = float(values.get(fieldname) or 0)
		except (TypeError, ValueError) as exc:
			raise ValueError(f"{fieldname} must be numeric") from exc
		if value < 0:
			raise ValueError(f"{fieldname} cannot be negative")
		result[fieldname] = value
	return result
