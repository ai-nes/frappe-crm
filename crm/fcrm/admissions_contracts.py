"""Shared contracts for the admissions ERD read model.

The module is deliberately framework-light so mapping and filter behaviour can
be verified without a running Frappe site.  Writers and readers may add data
sources behind these contracts, but clients only depend on this vocabulary.
"""

from __future__ import annotations

from datetime import date
from typing import Any

CONTRACT_VERSION = "admissions-erd-v1"
LIFECYCLE_MAPPING_VERSION = "admissions-lifecycle-v1"

PROJECTION_NAMES = (
	"AdmissionsOverview",
	"DigitalMarketingOverview",
	"FieldMarketingOverview",
	"Student360",
	"AICommandCenter",
)

ALLOWED_FILTERS = frozenset(
	{
		"admission_year",
		"from",
		"to",
		"from_date",
		"to_date",
		"granularity",
		"campus",
		"region",
		"territory",
		"major",
		"campaign",
		"channel",
		"owner",
		"team",
		"planning_scope",
		"metric_key",
		"source_system",
		"subject_grain",
		"status",
	}
)
ALLOWED_GRANULARITIES = frozenset({"day", "week", "month"})

# Values are intentionally explicit.  A dashboard stage is not a replacement
# for the operational lifecycle value and Lost remains a terminal dimension.
LIFECYCLE_STAGE_MAP = {
	"lead": "lead",
	"lead mới": "lead",
	"mql": "mql",
	"qualified": "mql",
	"có triển vọng": "mql",
	"applicant": "applicant",
	"đã nộp hồ sơ": "applicant",
	"enrolled": "enrolled",
	"đã nhập học": "enrolled",
	"lost": "lost",
	"không quan tâm": "lost",
	"sai số": "lost",
}


class ContractValidationError(ValueError):
	"""Raised when a public dashboard contract cannot be normalized safely."""


def dashboard_stage(value: Any) -> str | None:
	"""Map an operational lifecycle value to its versioned dashboard stage."""

	if value is None:
		return None
	key = str(value).strip().casefold()
	return LIFECYCLE_STAGE_MAP.get(key)


def lifecycle_reporting_dimension(
	value: Any, lost_reason: Any = None, evidence: Any = None
) -> dict[str, Any]:
	"""Return a loss-preserving reporting dimension.

	Unknown values are kept as ``unmapped`` instead of being silently coerced
	into an adjacent stage.  This makes incomplete migrations visible to parity
	reports and preserves the reason/evidence attached to Lost workflow rows.
	"""

	operational_value = None if value is None else str(value).strip()
	stage = dashboard_stage(operational_value)
	return {
		"mapping_version": LIFECYCLE_MAPPING_VERSION,
		"operational_stage": operational_value,
		"dashboard_stage": stage or "unmapped",
		"is_terminal": stage in {"enrolled", "lost"},
		"lost_reason": str(lost_reason).strip() if lost_reason else None,
		"evidence": evidence,
	}


def _as_scalar_or_list(value: Any, field: str) -> str | list[str] | None:
	if value is None or value == "":
		return None
	values = value if isinstance(value, (list, tuple, set)) else [value]
	cleaned = [str(item).strip() for item in values if str(item).strip()]
	if len(cleaned) > 100:
		raise ContractValidationError(f"{field} accepts at most 100 values")
	if isinstance(value, (list, tuple, set)):
		return sorted(set(cleaned))
	return cleaned[0] if cleaned else None


def _iso_date(value: Any, field: str) -> str | None:
	if value in (None, ""):
		return None
	try:
		return date.fromisoformat(str(value)).isoformat()
	except ValueError as exc:
		raise ContractValidationError(f"{field} must be an ISO date") from exc


def normalize_filters(filters: dict[str, Any] | None = None) -> dict[str, Any]:
	"""Validate and normalize the shared server-side projection filters."""

	if filters is None:
		filters = {}
	if not isinstance(filters, dict):
		raise ContractValidationError("filters must be an object")
	unknown = sorted(set(filters) - ALLOWED_FILTERS)
	if unknown:
		raise ContractValidationError(f"unsupported filters: {', '.join(unknown)}")

	normalized: dict[str, Any] = {
		"admission_year": _as_scalar_or_list(filters.get("admission_year"), "admission_year"),
		"campus": _as_scalar_or_list(filters.get("campus"), "campus"),
		"region": _as_scalar_or_list(filters.get("region"), "region"),
		"territory": _as_scalar_or_list(filters.get("territory"), "territory"),
		"major": _as_scalar_or_list(filters.get("major"), "major"),
		"campaign": _as_scalar_or_list(filters.get("campaign"), "campaign"),
		"channel": _as_scalar_or_list(filters.get("channel"), "channel"),
		"owner": _as_scalar_or_list(filters.get("owner"), "owner"),
		"team": _as_scalar_or_list(filters.get("team"), "team"),
		"planning_scope": _as_scalar_or_list(filters.get("planning_scope"), "planning_scope"),
		"metric_key": _as_scalar_or_list(filters.get("metric_key"), "metric_key"),
		"source_system": _as_scalar_or_list(filters.get("source_system"), "source_system"),
		"subject_grain": _as_scalar_or_list(filters.get("subject_grain"), "subject_grain"),
		"status": _as_scalar_or_list(filters.get("status"), "status"),
		"from_date": _iso_date(filters.get("from_date", filters.get("from")), "from"),
		"to_date": _iso_date(filters.get("to_date", filters.get("to")), "to"),
		"granularity": str(filters.get("granularity") or "day").strip().lower(),
	}
	if normalized["granularity"] not in ALLOWED_GRANULARITIES:
		raise ContractValidationError("granularity must be day, week, or month")
	if normalized["from_date"] and normalized["to_date"] and normalized["from_date"] > normalized["to_date"]:
		raise ContractValidationError("from must not be after to")
	return {key: value for key, value in normalized.items() if value is not None}


def empty_projection(name: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
	"""Build a safe empty response for a known projection."""

	if name not in PROJECTION_NAMES:
		raise ContractValidationError(f"unknown projection: {name}")
	return {
		"contract": CONTRACT_VERSION,
		"projection": name,
		"filters": normalize_filters(filters),
		"source": {
			"mode": "target",
			"status": "no_data",
			"mapping_version": LIFECYCLE_MAPPING_VERSION,
			"definition_version": CONTRACT_VERSION,
			"subject_grain": None,
			"stale": False,
		},
		"data": {},
		"warnings": [],
	}
