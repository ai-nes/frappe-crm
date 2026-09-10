"""Cohort parity and rollout-state helpers for the admissions cutover."""

from __future__ import annotations

from typing import Any


DEFAULT_TOLERANCES = {
	"student_count": 0,
	"application_count": 0,
	"submitted_count": 0,
	"enrolled_count": 0,
	"spend": 0.01,
	"recognized_revenue": 0.01,
	"attribution_weight": 0.0001,
}


def reconcile_cohort(
	legacy: dict[str, Any],
	target: dict[str, Any],
	*,
	tolerances: dict[str, float] | None = None,
) -> dict[str, Any]:
	"""Compare named metrics and report unexplained deltas as blockers."""

	limits = {**DEFAULT_TOLERANCES, **(tolerances or {})}
	metrics = sorted(set(legacy) | set(target))
	deltas = {}
	blockers = []
	for metric in metrics:
		legacy_value = float(legacy.get(metric) or 0)
		target_value = float(target.get(metric) or 0)
		delta = target_value - legacy_value
		within_tolerance = abs(delta) <= float(limits.get(metric, 0))
		deltas[metric] = {
			"legacy": legacy_value,
			"target": target_value,
			"delta": delta,
			"tolerance": float(limits.get(metric, 0)),
			"within_tolerance": within_tolerance,
		}
		if not within_tolerance:
			blockers.append(metric)
	return {"status": "blocked" if blockers else "parity", "deltas": deltas, "blockers": blockers}


def build_reconciliation_report(cohorts: list[dict[str, Any]]) -> dict[str, Any]:
	"""Reconcile each cohort while retaining only keyed metric evidence."""

	results = []
	for cohort in cohorts:
		result = reconcile_cohort(cohort.get("legacy", {}), cohort.get("target", {}), tolerances=cohort.get("tolerances"))
		results.append({"key": cohort.get("key", "unknown"), **result})
	blockers = [result["key"] for result in results if result["status"] == "blocked"]
	return {"status": "blocked" if blockers else "parity", "cohorts": results, "blockers": blockers}


def reader_rollout_state(stage: str) -> dict[str, Any]:
	"""Return an explicit reader state; rollback never deletes target facts."""

	if stage not in {"shadow", "canary", "target", "legacy"}:
		raise ValueError("reader stage must be shadow, canary, target, or legacy")
	return {
		"stage": stage,
		"reader": "legacy_projection" if stage == "legacy" else "target_projection",
		"comparison_enabled": stage in {"shadow", "canary"},
		"rollback": "switch reader to legacy_projection",
		"physical_delete": False,
	}
