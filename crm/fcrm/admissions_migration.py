"""Idempotent migration primitives shared by admissions backfills."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from typing import Any

MIGRATION_SCHEMA_VERSION = "admissions-migration-v1"
CANONICAL_MIGRATION_ORDER = (
	"offering_case_application",
	"stakeholder_snapshot_payment_revenue",
	"territory_geography",
	"campaign_fact_metric",
	"planning_scope_target_forecast",
	"projections",
)
LEGACY_PROFILE_FIELDS = {
	"CRM High School": ("school_code", "province", "ward"),
	"CRM Campus": ("campus_code", "province"),
	"CRM Major": ("major_code", "major_name"),
	"CRM Campaign": ("stable_code", "title", "platform"),
	"CRM Lead": ("admission_year", "branch", "major", "high_school"),
	"CRM Ward": ("ward_code", "province"),
}
PROVENANCE_FIELDS = (
	"schema_version",
	"source_doctype",
	"source_name",
	"source_reference",
	"idempotency_fingerprint",
)


def stable_fingerprint(*values: Any) -> str:
	"""Create a deterministic fingerprint for a source row and transformation."""

	payload = json.dumps(values, sort_keys=True, default=str, separators=(",", ":"))
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def provenance(
	*, source_doctype: str, source_name: str, source_reference: str | None = None, **values: Any
) -> dict[str, Any]:
	"""Return provenance fields suitable for any additive fact DocType."""

	return {
		"schema_version": MIGRATION_SCHEMA_VERSION,
		"source_doctype": str(source_doctype),
		"source_name": str(source_name),
		"source_reference": source_reference or f"{source_doctype}:{source_name}",
		"idempotency_fingerprint": stable_fingerprint(source_doctype, source_name, values),
	}


def profile_rows(rows: Iterable[dict[str, Any]], fields: Iterable[str]) -> dict[str, Any]:
	"""Produce null/duplicate counts without exposing row values in the report."""

	rows = list(rows)
	fields = list(fields)
	null_counts = {field: sum(row.get(field) in (None, "") for row in rows) for field in fields}
	duplicate_counts = {}
	for field in fields:
		counts = Counter(str(row[field]).strip() for row in rows if row.get(field) not in (None, ""))
		duplicate_counts[field] = sum(count - 1 for count in counts.values() if count > 1)
	return {
		"schema_version": MIGRATION_SCHEMA_VERSION,
		"row_count": len(rows),
		"null_counts": null_counts,
		"duplicate_counts": duplicate_counts,
	}


def migration_summary(outcomes: Iterable[str]) -> dict[str, int]:
	"""Count stable migration outcomes for dry-run and applied reports."""

	allowed = {"migrated", "existing", "review", "quarantined", "skipped", "invalid"}
	result = Counter(str(outcome) for outcome in outcomes)
	keys = sorted(allowed if result.get("quarantined") else allowed - {"quarantined"})
	return {key: result.get(key, 0) for key in keys}


def build_batch_report(
	*,
	run_key: str,
	phase: str,
	cursor: str | None,
	outcomes: Iterable[str],
	next_cursor: str | None = None,
	dry_run: bool = True,
) -> dict[str, Any]:
	"""Return a resumable, value-redacted report for one migration batch."""

	if phase not in CANONICAL_MIGRATION_ORDER:
		raise ValueError("phase is not in the canonical migration order")
	if not str(run_key or "").strip():
		raise ValueError("run_key is required")
	return {
		"schema_version": MIGRATION_SCHEMA_VERSION,
		"run_key": run_key,
		"phase": phase,
		"cursor": cursor,
		"next_cursor": next_cursor,
		"dry_run": bool(dry_run),
		"counts": migration_summary(outcomes),
	}


def build_baseline_report(rows_by_doctype: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
	"""Build a value-redacted, deterministic baseline from already-read rows."""

	profiles = {
		doctype: profile_rows(rows_by_doctype.get(doctype, []), fields)
		for doctype, fields in LEGACY_PROFILE_FIELDS.items()
	}
	return {
		"schema_version": MIGRATION_SCHEMA_VERSION,
		"mode": "dry_run",
		"profiles": profiles,
		"write_count": 0,
	}
