"""Deterministic Phase 5 migration/backfill planner.

The default operation is a dry run.  It maps only values that are already
explicitly present in Student or Enrollment Status metadata.  It never creates
an outcome, next action, qualification evidence, actor, reason or timestamp.
An operator may apply the small lifecycle projection update after reviewing the
quarantine report; append-only event streams are not fabricated by this patch.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

try:
	import frappe
except ImportError:  # pragma: no cover - pure mapping tests run outside bench
	frappe = None


VALID_LIFECYCLE_STAGES = frozenset({"Lead", "MQL", "Applicant", "Enrolled", "Lost"})


def map_legacy_lifecycle(student: dict[str, Any], status_rows: Iterable[dict[str, Any]] = ()) -> tuple[str | None, str]:
	"""Map one legacy Student deterministically to ``(stage, classification)``."""
	explicit = str(student.get("lifecycle_stage") or "").strip()
	if explicit in VALID_LIFECYCLE_STAGES:
		return explicit, "explicit"
	status = str(student.get("enrollment_status") or "").strip()
	if not status:
		return None, "missing_status"
	candidates = {
		str(row.get("lifecycle_stage") or "").strip()
		for row in status_rows
		if str(row.get("status_name") or row.get("name") or "").strip() == status
		and str(row.get("lifecycle_stage") or "").strip() in VALID_LIFECYCLE_STAGES
	}
	# A status that is itself a canonical stage is deterministic even if the
	# current master has not yet been extended with lifecycle_stage.
	if status in VALID_LIFECYCLE_STAGES:
		candidates.add(status)
	if len(candidates) == 1:
		return next(iter(candidates)), "status_metadata"
	if len(candidates) > 1:
		return None, "ambiguous_status_mapping"
	return None, "unmapped_status"


def classify_student(student: dict[str, Any], status_rows: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
	stage, classification = map_legacy_lifecycle(student, status_rows)
	return {
		"student": student.get("name"),
		"current_status": student.get("enrollment_status"),
		"current_stage": student.get("lifecycle_stage"),
		"mapped_stage": stage,
		"classification": classification,
		"would_update_lifecycle_projection": bool(stage and stage != student.get("lifecycle_stage")),
		"fabricated_events": 0,
	}


def build_dry_run_report(students: Iterable[dict[str, Any]], status_rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
	status_rows = list(status_rows)
	items = [classify_student(student, status_rows) for student in students]
	counts = Counter(item["classification"] for item in items)
	return {
		"dry_run": True,
		"policy_version": "phase5-release-v1",
		"students_checked": len(items),
		"projection_updates": sum(item["would_update_lifecycle_projection"] for item in items),
		"quarantined": sum(item["classification"] in {"ambiguous_status_mapping", "unmapped_status", "missing_status"} for item in items),
		"classifications": dict(sorted(counts.items())),
		"items": items,
		"fabricated_outcomes": 0,
		"fabricated_qualification_evidence": 0,
		"fabricated_next_actions": 0,
		"note": "Only explicit lifecycle/status metadata is mapped; no business event or actor is inferred.",
	}


def _load_rows() -> tuple[list[Any], list[Any]]:
	if frappe is None:
		raise RuntimeError("The Phase 5 migration requires a Frappe bench")
	students = frappe.get_all(
		"CRM Lead",
		fields=["name", "enrollment_status", "lifecycle_stage"],
		order_by="name asc",
	)
	status_fields = ["name", "status_name"]
	try:
		status_fields.append("lifecycle_stage")
		statuses = frappe.get_all("CRM Enrollment Status", fields=status_fields, order_by="name asc")
	except Exception:
		statuses = frappe.get_all("CRM Enrollment Status", fields=["name", "status_name"], order_by="name asc")
	return students, statuses


def execute():
	if not frappe.db.exists("DocType", "CRM Enrollment Status"):
		return {"status": "taxonomy_pending"}
	"""Run the safe default dry-run patch and return its report."""
	students, statuses = _load_rows()
	return build_dry_run_report(students, statuses)


def apply_deterministic_lifecycle_projection() -> dict[str, Any]:
	"""Apply only unambiguous lifecycle projections; never create event rows."""
	students, statuses = _load_rows()
	report = build_dry_run_report(students, statuses)
	updated = []
	for item in report["items"]:
		if not item["would_update_lifecycle_projection"]:
			continue
		if item["classification"] not in {"explicit", "status_metadata"}:
			continue
		frappe.db.set_value("CRM Lead", item["student"], "lifecycle_stage", item["mapped_stage"], update_modified=False)
		updated.append(item["student"])
	report["dry_run"] = False
	report["projection_updates_applied"] = updated
	return report
