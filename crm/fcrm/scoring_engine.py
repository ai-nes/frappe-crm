"""Deterministic rule scorers executed inside Frappe.

This module is intentionally independent of crm-agents.  It evaluates only
facts already owned by Frappe and returns the same contributor shape consumed
by ``append_score_if_current``.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from operator import eq, ge, gt, le, lt, ne
from typing import Any

from crm.fcrm.scoring_compute import compute_time_decay

logger = logging.getLogger(__name__)


def _contains(actual: Any, expected: Any) -> bool:
	return str(expected).casefold() in str(actual).casefold()


def _in(actual: Any, expected: Any) -> bool:
	values = {part.strip().casefold() for part in str(expected).split(",") if part.strip()}
	return str(actual).casefold() in values


_OPERATORS = {
	"=": eq,
	"!=": ne,
	">=": ge,
	"<=": le,
	">": gt,
	"<": lt,
	"contains": _contains,
	"in": _in,
}
_IMPORTANCE_SCORES = {"Very High": 90.0, "High": 70.0, "Medium": 50.0, "Low": 30.0, "Very Low": 10.0}
_DEFAULT_SUPPORTING_WEIGHT = 0.3


def parse_datetime(value: Any) -> datetime:
	if isinstance(value, datetime):
		return value
	return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _naive(value: datetime) -> datetime:
	return value.replace(tzinfo=None) if value.tzinfo is not None else value


def parse_importance(value: Any) -> float:
	if value is None or value == "":
		return 0.0
	if isinstance(value, (int, float)):
		return float(value)
	if value in _IMPORTANCE_SCORES:
		return _IMPORTANCE_SCORES[value]
	try:
		return float(value)
	except (TypeError, ValueError):
		return 0.0


@dataclass
class SignalContext:
	student: Any
	academic_results: list[dict]
	language_certs: list[dict]

	def get_field(self, field: str) -> Any:
		if field == "grade":
			return _latest_academic(self.academic_results).get("grade")
		if field == "gpa":
			return max((float(row.get("gpa") or 0) for row in self.academic_results), default=0.0)
		if field == "academic_rank":
			return _best_gpa_row(self.academic_results).get("academic_rank")
		if field == "ielts_score":
			return _ielts_score(self.language_certs)
		if hasattr(self.student, "get"):
			return self.student.get(field)
		return getattr(self.student, field, None)


def _latest_academic(rows: list[dict]) -> dict:
	if not rows:
		return {}
	try:
		return sorted(rows, key=lambda row: str(row.get("school_year", "")), reverse=True)[0]
	except Exception:
		return rows[-1]


def _best_gpa_row(rows: list[dict]) -> dict:
	return max(rows, key=lambda row: float(row.get("gpa") or 0), default={})


def _ielts_score(certs: list[dict]) -> float:
	best = 0.0
	for cert in certs:
		language = str(cert.get("language") or "").lower()
		name = str(cert.get("certificate_name") or "").lower()
		if "ielts" in language or "ielts" in name:
			try:
				best = max(best, float(cert.get("score_level") or 0))
			except (TypeError, ValueError):
				continue
	return best


def _coerce(actual: Any, expected: str) -> Any:
	if actual is None:
		return None
	try:
		if isinstance(actual, bool):
			return expected.lower() in ("true", "1", "yes")
		if isinstance(actual, (int, float)):
			return float(expected)
	except (TypeError, ValueError):
		return expected
	return expected


def eval_property(rule: dict, ctx: SignalContext) -> bool:
	field = rule.get("condition_field")
	if not field:
		return False
	actual = ctx.get_field(field)
	if actual is None:
		return False
	operator = _OPERATORS.get(rule.get("condition_operator", "="), eq)
	try:
		return bool(operator(actual, _coerce(actual, str(rule.get("condition_value", "")))))
	except (TypeError, ValueError):
		return False


def same_touchpoint(configured_key: str, actual_key: str | None) -> bool:
	return actual_key == configured_key


def eval_interaction(rule: dict, interactions: list[dict]) -> list[dict]:
	semantic_key = rule.get("interaction_semantic_key")
	if not semantic_key:
		return []
	return [row for row in interactions if same_touchpoint(semantic_key, row.get("interaction_semantic_key"))]


def eval_intent(rule: dict, intents: list[dict], reference_date: datetime | None = None) -> list[dict]:
	semantic_key = rule.get("intent_semantic_key")
	if not semantic_key:
		return []
	matched = []
	for intent in intents:
		if intent.get("intent_semantic_key") != semantic_key:
			continue
		if rule.get("intent_role") and intent.get("intent_role") != rule["intent_role"]:
			continue
		if rule.get("intent_polarity") and intent.get("polarity") != rule["intent_polarity"]:
			continue
		if float(intent.get("confidence") or 0) < float(rule.get("min_confidence") or 0):
			continue
		max_age_days = int(rule.get("intent_max_age_days") or 0)
		if max_age_days and reference_date:
			raw = (
				intent.get("interaction_date") or intent.get("interaction_datetime") or intent.get("creation")
			)
			try:
				age_days = max(0, (_naive(reference_date) - _naive(parse_datetime(raw))).days)
			except (TypeError, ValueError, AttributeError):
				continue
			if age_days > max_age_days:
				continue
		matched.append(intent)
	return matched


def eval_inactivity(rule: dict, interactions: list[dict], reference_date: datetime) -> bool:
	threshold_days = int(rule.get("inactivity_days") or 30)
	latest = None
	for interaction in interactions:
		raw = interaction.get("interaction_datetime")
		if not raw:
			continue
		try:
			datetime_value = _naive(parse_datetime(raw))
		except (TypeError, ValueError, AttributeError):
			continue
		if latest is None or datetime_value > latest:
			latest = datetime_value
	if latest is None:
		return True
	return max(0, (_naive(reference_date) - latest).days) >= threshold_days


@dataclass
class ComponentResult:
	score: float = 0.0
	details: list[dict] = field(default_factory=list)
	dominant_intent: str = "unknown"
	supporting_intents: list[str] = field(default_factory=list)


def _detail(category: str, rule: dict, score: float, signal: str | None = None, reason: str = "") -> dict:
	return {
		"category": category,
		"rule_id": rule["signal_key"],
		# Signal labels are human-facing and may contain punctuation or Unicode.
		# Score History Detail deliberately stores the stable rule key so every
		# internally generated row satisfies the contributor wire contract.
		"signal": signal if signal is not None else rule["signal_key"],
		"score": score,
		"reason": reason,
	}


def calculate_fit_score(student, academic_results, language_certs, rules) -> ComponentResult:
	ctx = SignalContext(student, academic_results, language_certs)
	total = 0.0
	details = []
	for rule in rules:
		if not rule.get("is_active", True) or rule.get("signal_type") != "property":
			continue
		try:
			triggered = eval_property(rule, ctx)
		except Exception as exc:
			logger.warning("fit_score: error evaluating signal=%s: %s", rule.get("signal_key"), exc)
			triggered = False
		if triggered:
			points = float(rule.get("base_points") or 0)
			total += points
			details.append(_detail("Fit", rule, points))
	return ComponentResult(score=max(0.0, min(total, 100.0)), details=details)


def calculate_engagement_score(interactions, rules) -> ComponentResult:
	total = 0.0
	details = []
	for rule in rules:
		if not rule.get("is_active", True) or rule.get("signal_type") != "interaction":
			continue
		matched = eval_interaction(rule, interactions)
		rule_total = 0.0
		rule_details = []
		for _ in matched:
			points = float(rule.get("base_points") or 0)
			rule_total += points
			rule_details.append(_detail("Engagement", rule, points))
		max_points = float(rule.get("max_points") or 0)
		if max_points and rule_total > max_points:
			total += max_points
			running = 0.0
			for detail in rule_details:
				if running + detail["score"] <= max_points:
					details.append(detail)
					running += detail["score"]
		else:
			total += rule_total
			details.extend(rule_details if not (max_points and rule_total > max_points) else [])
	return ComponentResult(score=max(0.0, min(total, 100.0)), details=details)


def _supporting_weight(rules) -> float:
	for rule in rules:
		if rule.get("signal_key") == "intent_supporting_weight":
			return float(rule.get("base_points") or _DEFAULT_SUPPORTING_WEIGHT)
	return _DEFAULT_SUPPORTING_WEIGHT


def _intent_date_value(intent: dict) -> float:
	raw = intent.get("interaction_date") or intent.get("interaction_datetime") or intent.get("creation")
	if not raw:
		return float("-inf")
	try:
		return parse_datetime(raw).timestamp()
	except (TypeError, ValueError, AttributeError, OverflowError):
		return float("-inf")


def _intent_decay(intent: dict, reference_date: datetime | None, config) -> float:
	if reference_date is None:
		return 1.0
	raw = intent.get("interaction_date") or intent.get("interaction_datetime") or intent.get("creation")
	if not raw:
		return 1.0
	try:
		days = max(0, (_naive(reference_date) - _naive(parse_datetime(raw))).days)
	except (TypeError, ValueError, AttributeError):
		return 1.0
	return compute_time_decay(days, config or [])


def calculate_intent_score(intents, rules, reference_date=None, time_decay_config=None) -> ComponentResult:
	if not intents:
		return ComponentResult()
	weight = _supporting_weight(rules)
	dominant = [intent for intent in intents if intent.get("intent_role") == "Dominant"]
	if not dominant:
		dominant = [
			max(
				intents,
				key=lambda intent: (
					parse_importance(intent.get("importance")),
					_intent_date_value(intent),
					str(intent.get("name") or ""),
				),
			)
		]
	dominant_names = {intent.get("name") for intent in dominant}
	intent_rules = [
		rule for rule in rules if rule.get("signal_type") == "intent" and rule.get("is_active", True)
	]
	total = 0.0
	details = []
	dominant_label = "unknown"
	supporting = []
	for rule in intent_rules:
		for intent in eval_intent(rule, intents, reference_date):
			raw_points = float(rule.get("base_points") or 0)
			points = raw_points if intent.get("name") in dominant_names else raw_points * weight
			decay = _intent_decay(intent, reference_date, time_decay_config)
			if intent.get("polarity") == "Negative":
				points = -points * decay
			else:
				points *= decay
			label = intent.get("intent_type") or intent.get("name") or "?"
			reason = f"polarity={intent.get('polarity') or 'Positive'}, decay={decay:.2f}, raw_points={raw_points:g}"
			if intent.get("name") in dominant_names:
				dominant_label = label
				details.append(
					_detail("Intent", rule, points, signal=f"Dominant {rule['signal_key']}", reason=reason)
				)
			else:
				supporting.append(label)
				details.append(
					_detail(
						"Intent",
						rule,
						points,
						signal=f"Support {rule['signal_key']}",
						reason=f"{reason}, weight={weight}",
					)
				)
			total += points
	return ComponentResult(
		score=max(0.0, min(total, 100.0)),
		details=details,
		dominant_intent=dominant_label,
		supporting_intents=supporting,
	)


def calculate_negative_score(interactions, negative_rules, reference_date) -> ComponentResult:
	inactivity_rules = sorted(
		(
			row
			for row in negative_rules
			if row.get("is_active", True) and row.get("signal_type") == "inactivity"
		),
		key=lambda row: int(row.get("inactivity_days") or 0),
		reverse=True,
	)
	event_rules = [
		row
		for row in negative_rules
		if row.get("is_active", True) and row.get("signal_type") == "interaction"
	]
	negative_keys = {
		row.get("interaction_semantic_key") for row in event_rules if row.get("interaction_semantic_key")
	}
	positive_interactions = [
		row
		for row in interactions
		if not any(same_touchpoint(key, row.get("interaction_semantic_key")) for key in negative_keys)
	]
	total = 0.0
	details = []
	for rule in inactivity_rules:
		if eval_inactivity(rule, positive_interactions, reference_date):
			points = -abs(float(rule.get("penalty_amount") or 0))
			details.append(_detail("Negative", rule, points, reason=""))
			total += points
			break
	for rule in event_rules:
		max_penalties = int(rule.get("max_penalties") or 0)
		matches = eval_interaction(rule, interactions)
		for count, _ in enumerate(matches):
			if max_penalties and count >= max_penalties:
				break
			points = -abs(float(rule.get("penalty_amount") or 0))
			details.append(_detail("Negative", rule, points, reason=""))
			total += points
	return ComponentResult(score=total, details=details)


def score_components(
	*, student, academic_results, language_certs, interactions, intents, policy, reference_date
) -> dict:
	"""Evaluate all four components from a resolved Frappe policy."""
	rules = policy.get("rules", [])
	fit = calculate_fit_score(
		student,
		academic_results,
		language_certs,
		[row for row in rules if row.get("category") == "Fit"],
	)
	engagement = calculate_engagement_score(
		interactions,
		[row for row in rules if row.get("category") == "Engagement"],
	)
	intent = calculate_intent_score(
		intents,
		[row for row in rules if row.get("category") == "Intent"],
		reference_date,
		policy.get("time_decay_config", []),
	)
	negative = calculate_negative_score(interactions, policy.get("negative_rules", []), reference_date)
	return {
		"fit": fit,
		"engagement": engagement,
		"intent": intent,
		"negative": negative,
	}
