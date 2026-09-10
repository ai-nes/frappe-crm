"""Configuration-only controls for the Interaction Intelligence cutover."""

from __future__ import annotations

from collections import Counter
from typing import Any

CANONICAL_WRITER = "canonical_interaction_command"
REQUIRED_THRESHOLDS = frozenset(
	{
		"duplicate_rate",
		"drop_rate",
		"analysis_failure_rate",
		"analysis_latency_p95_s",
		"intent_parity_delta",
		"score_parity_delta",
		"authorization_error_rate",
	}
)


def _number(value: Any, key: str) -> float:
	try:
		result = float(value)
	except (TypeError, ValueError) as exc:
		raise ValueError(f"{key} must be numeric") from exc
	if result < 0:
		raise ValueError(f"{key} must not be negative")
	return result


def validate_routing_manifest(manifest: dict[str, Any] | None) -> dict[str, Any]:
	"""Validate a declarative source/cohort manifest without applying it."""
	manifest = manifest or {}
	sources = manifest.get("sources")
	if not isinstance(sources, dict) or not sources:
		return {"status": "blocked", "blockers": ["missing_sources"], "sources": {}}
	blockers: list[str] = []
	resolved: dict[str, dict[str, Any]] = {}
	for source, config in sorted(sources.items()):
		config = config if isinstance(config, dict) else {}
		writer = str(config.get("writer") or "")
		ledger_namespace = str(config.get("ledger_namespace") or "")
		cohorts = config.get("cohorts")
		if writer != CANONICAL_WRITER:
			blockers.append(f"{source}:writer_not_canonical")
		if not ledger_namespace:
			blockers.append(f"{source}:missing_ledger_namespace")
		if not isinstance(cohorts, dict) or not cohorts:
			blockers.append(f"{source}:missing_cohorts")
			cohorts = {}
		for cohort, state in cohorts.items():
			if not isinstance(state, dict) or not isinstance(state.get("enabled"), bool):
				blockers.append(f"{source}:{cohort}:missing_enabled_flag")
		resolved[str(source)] = {
			"writer": writer,
			"ledger_namespace": ledger_namespace,
			"cohorts": {
				str(key): bool(value.get("enabled"))
				for key, value in cohorts.items()
				if isinstance(value, dict)
			},
		}
	return {"status": "blocked" if blockers else "ready", "blockers": blockers, "sources": resolved}


def evaluate_acceptance_gates(
	metrics: dict[str, Any] | None,
	thresholds: dict[str, Any] | None,
) -> dict[str, Any]:
	"""Compare aggregate measurements with explicit, operator-supplied gates."""
	metrics, thresholds = metrics or {}, thresholds or {}
	missing_thresholds = sorted(REQUIRED_THRESHOLDS - set(thresholds))
	missing_metrics = sorted(REQUIRED_THRESHOLDS - set(metrics))
	if missing_thresholds or missing_metrics:
		return {
			"status": "blocked",
			"blockers": [
				*[f"missing_threshold:{key}" for key in missing_thresholds],
				*[f"missing_metric:{key}" for key in missing_metrics],
			],
			"gates": {},
		}
	gates: dict[str, dict[str, Any]] = {}
	blockers = []
	for key in sorted(REQUIRED_THRESHOLDS):
		observed, allowed = _number(metrics[key], key), _number(thresholds[key], key)
		passed = observed <= allowed
		gates[key] = {"observed": observed, "allowed": allowed, "passed": passed}
		if not passed:
			blockers.append(key)
	return {"status": "ready" if not blockers else "blocked", "blockers": blockers, "gates": gates}


def compare_replay_receipts(canonical: list[dict[str, Any]], shadow: list[dict[str, Any]]) -> dict[str, Any]:
	"""Compare replay facts without returning event bodies or identifiers."""

	def fingerprint(row: dict[str, Any]) -> tuple:
		return (
			str(row.get("event_key") or ""),
			str(row.get("episode_key") or ""),
			str(row.get("intent_term") or ""),
			str(row.get("intent_state") or ""),
			str(row.get("score_components_digest") or ""),
			bool(row.get("authorized", False)),
		)

	left, right = Counter(fingerprint(row) for row in canonical), Counter(fingerprint(row) for row in shadow)
	return {
		"canonical_receipts": sum(left.values()),
		"shadow_receipts": sum(right.values()),
		"unmatched_canonical": sum((left - right).values()),
		"unmatched_shadow": sum((right - left).values()),
		"status": "parity" if left == right else "blocked",
	}


def dry_run_report(
	manifest: dict[str, Any] | None, metrics: dict[str, Any] | None, thresholds: dict[str, Any] | None
) -> dict[str, Any]:
	"""Build the non-mutating release decision record for a planned cohort."""
	routing = validate_routing_manifest(manifest)
	gates = evaluate_acceptance_gates(metrics, thresholds)
	blockers = [*routing["blockers"], *gates["blockers"]]
	return {
		"dry_run": True,
		"status": "ready" if not blockers else "blocked",
		"blockers": blockers,
		"routing": routing,
		"acceptance_gates": gates,
		"rollback": {
			"writer": CANONICAL_WRITER,
			"action": "route_new_events_to_last_validated_canonical_version",
		},
	}
