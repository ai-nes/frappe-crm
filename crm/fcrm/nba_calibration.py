"""Deterministic, reviewable calibration math for governed NBA policy proposals.

This module has no Frappe/database dependency.  Persistence and approval stay
in the CRM control plane; the helpers only accept explicit attribution rows and
return a digestible report.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from crm.fcrm.nba_canonical import canonical_digest

WEIGHT_KEYS = ("opportunity_fit", "urgency", "effectiveness_index")
TERMINAL_LABELS = frozenset({"enrolled", "lost", "withdrawn"})


def select_attribution_dataset(rows: Iterable[Mapping], *, cohort_key: str, season: str) -> dict:
	"""Keep only explicit, terminally-labelled attribution links."""
	included = []
	exclusions = []
	for row in rows:
		missing = [
			field
			for field in ("evaluation", "recommendation", "action_execution", "terminal_result_revision")
			if not row.get(field)
		]
		if row.get("cohort_key") != cohort_key or str(row.get("season") or "") != season:
			missing.append("cohort_scope")
		label = str(row.get("label") or "").casefold()
		if label not in TERMINAL_LABELS:
			missing.append("terminal_label")
		if missing:
			exclusions.append({"row": str(row.get("name") or "unknown"), "reason": ",".join(sorted(set(missing)))})
			continue
		included.append(
			{
				"evaluation": str(row["evaluation"]),
				"recommendation": str(row["recommendation"]),
				"action_execution": str(row["action_execution"]),
				"terminal_result_revision": str(row["terminal_result_revision"]),
				"label": label,
				"components": dict(row.get("components") or {}),
			}
		)
	included.sort(key=lambda row: (row["evaluation"], row["recommendation"], row["action_execution"]))
	exclusions.sort(key=lambda row: (row["row"], row["reason"]))
	return {
		"cohort_key": cohort_key,
		"season": season,
		"rows": included,
		"exclusions": exclusions,
		"dataset_digest": canonical_digest({"rows": included, "exclusions": exclusions}),
	}


def validate_component_weights(weights: Mapping) -> dict[str, float]:
	if not isinstance(weights, Mapping) or set(weights) != set(WEIGHT_KEYS):
		raise ValueError("candidate weights must contain exactly the three kernel components")
	result = {key: float(weights[key]) for key in WEIGHT_KEYS}
	if any(not math.isfinite(value) or value < 0 for value in result.values()):
		raise ValueError("candidate weights must be finite and non-negative")
	if not math.isclose(sum(result.values()), 1.0, abs_tol=1e-9):
		raise ValueError("candidate weights must sum to one")
	return result


def score_weight_candidate(rows: Iterable[Mapping], weights: Mapping) -> dict:
	"""Score a candidate without inferring outcomes from a student/cohort join."""
	weights = validate_component_weights(weights)
	rows = list(rows)
	if not rows:
		return {"n": 0, "metric": None, "weights": weights}
	hits = 0
	for row in rows:
		components = row.get("components") or {}
		value = sum(float(components.get(key) or 0.0) * weights[key] for key in WEIGHT_KEYS)
		predicted = value >= 0.5
		actual = str(row.get("label")) == "enrolled"
		hits += int(predicted == actual)
	return {"n": len(rows), "metric": round(hits / len(rows), 6), "weights": weights}


def build_calibration_report(dataset: Mapping, candidates: Iterable[Mapping], *, baseline: Mapping) -> dict:
	rows = list(dataset.get("rows") or [])
	results = [score_weight_candidate(rows, candidate) for candidate in candidates]
	results.sort(key=lambda item: (-float(item["metric"] or -1), tuple(item["weights"][key] for key in WEIGHT_KEYS)))
	report = {
		"dataset_digest": dataset.get("dataset_digest"),
		"baseline": score_weight_candidate(rows, baseline),
		"candidates": results,
		"promotion": {"status": "shadow_only", "approved": False},
	}
	report["report_digest"] = canonical_digest({key: value for key, value in report.items() if key != "report_digest"})
	return report
