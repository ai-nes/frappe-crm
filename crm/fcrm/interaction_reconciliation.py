"""Deployment-time reconciliation for legacy CRM Interaction rows.

The canonical interaction intake command owns ``external_id`` for new rows.
This module only repairs legacy rows that already carry both source identity
fields.  It is intentionally dry-run by default and never guesses an identity
for rows without an explicit source namespace and record id.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import frappe


MAX_EXTERNAL_ID_LENGTH = 140


def _candidate_external_id(row: dict[str, Any]) -> str | None:
	"""Return the canonical source identity, or ``None`` if it is incomplete."""
	namespace = str(row.get("source_namespace") or "").strip()
	record_id = str(row.get("source_record_id") or "").strip()
	if not namespace or not record_id:
		return None
	return f"{namespace}:{record_id}"


def _plan_backfill(
	rows: list[dict[str, Any]],
	existing_external_ids: dict[str, int],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
	"""Build a non-mutating backfill plan and its explicit conflicts."""
	candidates: list[dict[str, str]] = []
	conflicts: list[dict[str, str]] = []
	for row in rows:
		candidate = _candidate_external_id(row)
		if candidate is None:
			conflicts.append({"name": str(row.get("name")), "reason": "missing_source_identity"})
			continue
		if len(candidate) > MAX_EXTERNAL_ID_LENGTH:
			conflicts.append(
				{
					"name": str(row.get("name")),
					"external_id": candidate[:MAX_EXTERNAL_ID_LENGTH],
					"reason": "external_id_too_long",
				}
			)
			continue
		candidates.append({"name": str(row.get("name")), "external_id": candidate})

	counts = Counter(item["external_id"] for item in candidates)
	eligible: list[dict[str, str]] = []
	for item in candidates:
		external_id = item["external_id"]
		if counts[external_id] > 1:
			conflicts.append({**item, "reason": "duplicate_candidate"})
		elif existing_external_ids.get(external_id, 0):
			conflicts.append({**item, "reason": "external_id_exists"})
		else:
			eligible.append(item)
	return eligible, conflicts


def _existing_external_id_counts(external_ids: list[str]) -> dict[str, int]:
	if not external_ids:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT external_id, COUNT(*) AS row_count
		FROM `tabCRM Interaction`
		WHERE external_id IN %(external_ids)s
		GROUP BY external_id
		""",
		{"external_ids": tuple(external_ids)},
		as_dict=True,
	)
	return {str(row["external_id"]): int(row["row_count"]) for row in rows}


def _existing_duplicate_external_ids() -> list[dict[str, Any]]:
	rows = frappe.db.sql(
		"""
		SELECT external_id, COUNT(*) AS row_count
		FROM `tabCRM Interaction`
		WHERE external_id IS NOT NULL AND external_id != ''
		GROUP BY external_id
		HAVING COUNT(*) > 1
		ORDER BY external_id
		""",
		as_dict=True,
	)
	return [
		{"external_id": str(row["external_id"]), "row_count": int(row["row_count"])}
		for row in rows
	]


def reconcile_interaction_external_ids(*, dry_run: bool = True) -> dict[str, Any]:
	"""Report or apply safe legacy ``CRM Interaction.external_id`` backfill.

	``dry_run=True`` is the safe default.  The caller owns the surrounding
	transaction; this function deliberately does not commit.  Conflicting,
	ambiguous, incomplete, or overlong identities are reported and skipped.
	"""
	rows = frappe.db.sql(
		"""
		SELECT name, source_namespace, source_record_id
		FROM `tabCRM Interaction`
		WHERE (external_id IS NULL OR external_id = '')
		ORDER BY name
		""",
		as_dict=True,
	)
	existing_duplicates = _existing_duplicate_external_ids()
	candidate_ids = [
		candidate
		for row in rows
		if (candidate := _candidate_external_id(row)) is not None
	]
	existing = _existing_external_id_counts(sorted(set(candidate_ids)))
	eligible, conflicts = _plan_backfill(list(rows), existing)
	updated: list[str] = []
	# Candidate-level conflicts are skipped while unrelated safe rows can still
	# be repaired.  Existing duplicate external IDs are a batch-level integrity
	# problem, so explicit apply is blocked until the operator resolves them.
	apply_blocked = bool(existing_duplicates)
	if not dry_run and not apply_blocked:
		for item in eligible:
			try:
				frappe.db.set_value(
					"CRM Interaction",
					item["name"],
					"external_id",
					item["external_id"],
					update_modified=False,
				)
				updated.append(item["name"])
			except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
				apply_blocked = True
				conflicts.append({**item, "reason": "unique_constraint_race"})
	return {
		"dry_run": dry_run,
		"scanned": len(rows),
		"eligible": len(eligible),
		"would_backfill": len(eligible) if dry_run and not apply_blocked else 0,
		"backfilled": len(updated),
		"apply_blocked": apply_blocked,
		"existing_duplicate_external_ids": existing_duplicates,
		"conflicts": conflicts,
		"existing_external_id_counts": existing,
		"updated_names": updated,
	}


def run(*, apply: bool = False) -> dict[str, Any]:
	"""Bench-executable entry point; mutation requires explicit ``apply=True``."""
	return reconcile_interaction_external_ids(dry_run=not apply)


__all__ = [
	"MAX_EXTERNAL_ID_LENGTH",
	"reconcile_interaction_external_ids",
	"run",
]
