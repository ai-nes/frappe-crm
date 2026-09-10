"""Small, framework-independent contracts for canonical admissions facts.

Frappe document classes call these helpers so the business rules are also
testable during migration dry-runs, where no site or database is available.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any

CANONICAL_SCHEMA_VERSION = "admissions-erd"
OFFERING_STATUSES = frozenset({"Draft", "Pending Approval", "Active", "Closed", "Retired"})
FUNNEL_GRAINS = frozenset({"Case", "Application"})
SCOPE_FIELDS = ("region", "territory", "province", "team", "campus", "major")
ALLOWED_SCOPE_COMBINATIONS = frozenset(
	{
		(),
		("region",),
		("territory",),
		("province",),
		("team",),
		("campus",),
		("major",),
		("campus", "major"),
		("territory", "team"),
	}
)


def _required_text(values: dict[str, Any], fieldname: str) -> str:
	value = str(values.get(fieldname) or "").strip()
	if not value:
		raise ValueError(f"{fieldname} is required")
	return value


def _iso_date(value: Any, fieldname: str) -> str:
	try:
		return date.fromisoformat(str(value)).isoformat()
	except (TypeError, ValueError) as exc:
		raise ValueError(f"{fieldname} must be an ISO date") from exc


def canonical_case_key(identity: str, admission_year: str) -> str:
	"""Return a readable deterministic key for one identity/cycle pair."""

	identity_value = str(identity or "").strip()
	year_value = str(admission_year or "").strip()
	if not identity_value or not year_value:
		raise ValueError("identity and admission_year are required")
	slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", identity_value).strip("-") or "identity"
	key = f"CK-{slug}-{year_value}"
	if len(key) <= 140:
		return key
	digest = hashlib.sha256(f"{identity_value}|{year_value}".encode()).hexdigest()[:48]
	return f"CK-{digest}-{year_value}"[:140]


def canonical_attempt_key(case_key: str, offering: str, source_reference: str) -> str:
	"""Return the immutable business identity of one application attempt."""

	case_value = str(case_key or "").strip()
	offering_value = str(offering or "").strip()
	source_value = str(source_reference or "").strip()
	if not case_value or not offering_value or not source_value:
		raise ValueError("case_key, offering and source_reference are required")
	digest = hashlib.sha256(f"{case_value}|{offering_value}|{source_value}".encode()).hexdigest()
	return f"ATT-{digest}"


def validate_offering(values: dict[str, Any]) -> dict[str, Any]:
	"""Validate the catalog identity and effective interval of an offering."""

	for fieldname in ("admission_year", "campus", "major", "admission_method"):
		_required_text(values, fieldname)
	try:
		quota = int(values.get("quota"))
	except (TypeError, ValueError) as exc:
		raise ValueError("quota must be a non-negative integer") from exc
	if quota < 0:
		raise ValueError("quota must be a non-negative integer")
	status = str(values.get("status") or "Draft").strip()
	if status not in OFFERING_STATUSES:
		raise ValueError("status is invalid")
	start = _iso_date(values.get("effective_from"), "effective_from")
	end = _iso_date(values.get("effective_until"), "effective_until")
	if start > end:
		raise ValueError("effective_until must not be before effective_from")
	return {"quota": quota, "status": status, "effective_from": start, "effective_until": end}


def normalize_planning_scope(values: dict[str, Any]) -> dict[str, Any]:
	"""Normalize an allow-listed Link combination into a deterministic key."""

	if not isinstance(values, dict):
		raise ValueError("planning scope must be an object")
	unknown = sorted(set(values) - {*SCOPE_FIELDS, "scope_key"})
	if unknown:
		raise ValueError(f"unsupported scope fields: {', '.join(unknown)}")
	cleaned = {
		fieldname: str(values.get(fieldname) or "").strip()
		for fieldname in SCOPE_FIELDS
		if str(values.get(fieldname) or "").strip()
	}
	combination = tuple(fieldname for fieldname in SCOPE_FIELDS if fieldname in cleaned)
	if combination not in ALLOWED_SCOPE_COMBINATIONS:
		raise ValueError("planning scope combination is not allow-listed")
	scope_key = "|".join(f"{fieldname}:{cleaned[fieldname]}" for fieldname in combination) or "national"
	provided_key = str(values.get("scope_key") or "").strip()
	if provided_key and provided_key != scope_key:
		raise ValueError("scope_key does not match scope Links")
	return {"scope_key": scope_key, **cleaned}


def validate_fact_envelope(values: dict[str, Any]) -> dict[str, Any]:
	"""Validate lineage and correction metadata shared by immutable facts."""

	for fieldname in (
		"timezone",
		"source_system",
		"recorded_at",
		"idempotency_fingerprint",
		"normalized_dimension",
	):
		_required_text(values, fieldname)
	# Older canonical facts use ``source_run`` while campaign facts expose the
	# equivalent integration lineage as ``ingestion_run``.  Accept either name
	# without weakening the required lineage contract.
	if not str(values.get("source_run") or values.get("ingestion_run") or "").strip():
		raise ValueError("source_run or ingestion_run is required")
	start = _iso_date(values.get("period_start"), "period_start")
	end = _iso_date(values.get("period_end"), "period_end")
	if start > end:
		raise ValueError("period_end must not be before period_start")
	try:
		revision = int(values.get("revision"))
	except (TypeError, ValueError) as exc:
		raise ValueError("revision must be a positive integer") from exc
	if revision < 1:
		raise ValueError("revision must be a positive integer")
	supersedes = str(values.get("supersedes") or "").strip()
	if revision > 1 and not supersedes:
		raise ValueError("supersedes is required for a correction revision")
	if revision == 1 and supersedes:
		raise ValueError("revision 1 cannot supersede another fact")
	return {"period_start": start, "period_end": end, "revision": revision, "supersedes": supersedes or None}


def validate_metric_definition(values: dict[str, Any]) -> dict[str, Any]:
	"""Validate the semantic contract used to derive one dashboard metric."""

	for fieldname in ("metric_key", "unit", "aggregation", "timezone", "stage_mapping_version"):
		_required_text(values, fieldname)
	grain = _required_text(values, "subject_grain")
	if grain not in FUNNEL_GRAINS:
		raise ValueError("subject_grain must be Case or Application")
	return {"metric_key": str(values["metric_key"]).strip(), "subject_grain": grain}
