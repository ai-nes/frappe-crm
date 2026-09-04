"""Eligibility and decision-policy services for the NBA control plane.

Frappe is the sole authority for which actions a student may participate in:
the pure core here decides participation from catalog rows plus a few bounded
signals, and the AI evaluation service never re-interprets that verdict. The
Frappe wrappers gather the rows and fail closed on an out-of-scope student.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime

from crm.fcrm.action_type_catalog import ACTION_TYPE_CODES, action_category
from crm.fcrm.nba_canonical import (
	action_definition_snapshot,
	canonical_digest,
	json_string_list,
)

EXCLUSION_REASONS: frozenset[str] = frozenset(
	{
		"DISABLED",
		"NOT_EFFECTIVE",
		"EXPIRED",
		"ACTOR_NOT_ALLOWED",
		"COOLDOWN",
		"FREQUENCY_CAP",
		"CONSENT_MISSING",
		"OUT_OF_SCOPE",
		"UNKNOWN_CODE",
	}
)

_ACTIVE_POLICY_FIELDS = (
	"name",
	"policy_key",
	"policy_revision",
	"policy_digest",
	"top_n",
	"max_recommendations",
	"min_score_threshold",
	"score_weights",
	"conflict_key_fields",
	"diversity_rule",
)


def _coerce_datetime(value: object) -> datetime | None:
	if value in (None, ""):
		return None
	if isinstance(value, datetime):
		return value.replace(tzinfo=None)
	try:
		return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
	except ValueError:
		return None


def _actor_list(value: object) -> list[str]:
	snapshot = action_definition_snapshot({"allowed_actors": value})
	return snapshot["allowed_actors"]


def _row_digest(row: Mapping[str, object]) -> str:
	"""Always re-derive the digest from the row's live fields.

	The stored ``definition_digest`` column is a non-authoritative cache: nothing
	keeps it fresh when an admin edits the Action, so trusting it would let a
	stale value cross the boundary. The snapshot is deterministic, so recomputing
	here is the source of truth.
	"""
	return canonical_digest(action_definition_snapshot(row))


def _row_revision(row: Mapping[str, object]) -> int:
	try:
		return max(int(row.get("definition_revision") or 1), 1)
	except (TypeError, ValueError):
		return 1


def filter_eligible_actions(
	catalog_rows: Iterable[Mapping[str, object]],
	*,
	now: datetime,
	actor_roles: set[str] | None = None,
	recent_action_codes: Mapping[str, int] | None = None,
	cooldown_by_code: Mapping[str, int] | None = None,
) -> dict:
	"""Split catalog rows into the eligible set and an explained exclusion list.

	``now`` anchors the effective-window checks. ``actor_roles`` restricts the
	set to actions the actor may run (``System Manager`` bypasses the check).
	When both ``recent_action_codes`` and ``cooldown_by_code`` carry a code, a
	recent count at or above the cap excludes the action as ``FREQUENCY_CAP``.
	"""
	actions: list[dict] = []
	exclusions: list[dict] = []
	roles = {str(r) for r in actor_roles} if actor_roles is not None else None

	for row in catalog_rows:
		code = row.get("code")
		if not code or code not in ACTION_TYPE_CODES:
			exclusions.append({"action": str(code) if code else "", "reason": "UNKNOWN_CODE"})
			continue
		snapshot = action_definition_snapshot(row)
		if not snapshot["enabled"]:
			exclusions.append({"action": code, "reason": "DISABLED"})
			continue
		effective_from = _coerce_datetime(row.get("effective_from"))
		if effective_from and effective_from > now:
			exclusions.append({"action": code, "reason": "NOT_EFFECTIVE"})
			continue
		effective_to = _coerce_datetime(row.get("effective_to"))
		if effective_to and effective_to < now:
			exclusions.append({"action": code, "reason": "EXPIRED"})
			continue
		allowed_actors = snapshot["allowed_actors"]
		if (
			roles is not None
			and "System Manager" not in roles
			and allowed_actors
			and roles.isdisjoint(allowed_actors)
		):
			exclusions.append({"action": code, "reason": "ACTOR_NOT_ALLOWED"})
			continue
		if recent_action_codes is not None and cooldown_by_code is not None:
			cap = cooldown_by_code.get(code)
			seen = recent_action_codes.get(code, 0)
			if cap is not None and seen >= cap:
				exclusions.append({"action": code, "reason": "FREQUENCY_CAP"})
				continue
		actions.append(
			{
				"code": code,
				"revision": _row_revision(row),
				"digest": _row_digest(row),
				"category": snapshot["category"] or action_category(code),
				"default_channel": snapshot["default_channel"],
				"allowed_actors": allowed_actors,
				"purpose": snapshot["purpose"],
			}
		)

	actions.sort(key=lambda item: item["code"])
	exclusions.sort(key=lambda item: (item["action"], item["reason"]))
	return {"actions": actions, "exclusions": exclusions}


_DIVERSITY_RULES = frozenset({"none", "unique_action_type", "unique_category"})


def validate_decision_policy_numbers(
	top_n: object, max_recommendations: object, min_score_threshold: object
) -> None:
	"""Range-check the numeric knobs of an NBA Decision Policy.

	Raises ``ValueError`` with a specific message on the first violation so the
	same check backs both the pure tests and the DocType ``validate`` hook.
	"""
	try:
		top_n = int(top_n)
		max_recommendations = int(max_recommendations)
		min_score_threshold = float(min_score_threshold)
	except (TypeError, ValueError) as exc:
		raise ValueError("Decision policy numbers must be numeric.") from exc
	if top_n < 1:
		raise ValueError("top_n must be at least 1.")
	if max_recommendations < 1 or max_recommendations > 50:
		raise ValueError("max_recommendations must be between 1 and 50.")
	if top_n > max_recommendations:
		raise ValueError("top_n cannot exceed max_recommendations.")
	if not 0.0 <= min_score_threshold <= 1.0:
		raise ValueError("min_score_threshold must be within [0, 1].")


def validate_score_weights(weights: object) -> dict:
	"""Return the parsed ``score_weights`` object or raise ``ValueError``."""
	if weights in (None, ""):
		return {}
	if isinstance(weights, str):
		try:
			weights = json.loads(weights)
		except json.JSONDecodeError as exc:
			raise ValueError("score_weights must be a JSON object.") from exc
	if not isinstance(weights, Mapping):
		raise ValueError("score_weights must be a JSON object.")
	for key, value in weights.items():
		if not isinstance(key, str) or isinstance(value, bool) or not isinstance(value, (int, float)):
			raise ValueError("score_weights must map strings to numbers.")
	return dict(weights)


def validate_diversity_rule(rule: object) -> str:
	rule = str(rule or "none")
	if rule not in _DIVERSITY_RULES:
		raise ValueError(f"Unsupported diversity_rule: {rule}.")
	return rule


def decision_policy_digest_payload(row: Mapping[str, object]) -> dict:
	"""Bounded dict digested for an NBA Decision Policy ``policy_digest``."""
	return {
		"top_n": int(row.get("top_n") or 0),
		"max_recommendations": int(row.get("max_recommendations") or 0),
		"min_score_threshold": float(row.get("min_score_threshold") or 0),
		"score_weights": validate_score_weights(row.get("score_weights")),
		"conflict_key_fields": json_string_list(row.get("conflict_key_fields")),
		"diversity_rule": str(row.get("diversity_rule") or "none"),
	}


def wire_action_id(code: str | None) -> str:
	"""The ``action_id`` a code takes on the NBA Evaluation v1 wire (``ACT-<CODE>``)."""
	return f"ACT-{code}" if code else ""


def eligible_set_digest(actions: list[dict]) -> str:
	"""Digest of the eligible set reduced to the wire ``{action_id, revision, digest}``.

	Uses the same ``ACT-<CODE>`` identity the envelope emits so a consumer that
	recomputes ``set_digest`` from ``eligible_action_set.actions`` gets this value.
	"""
	reduced = sorted(
		(
			{
				"action_id": action.get("action_id") or wire_action_id(action.get("code")),
				"revision": int(action.get("revision") or action.get("action_revision") or 1),
				"digest": action.get("digest") or action.get("action_digest"),
			}
			for action in actions
		),
		key=lambda item: str(item["action_id"]),
	)
	return canonical_digest(reduced)


# --------------------------------------------------------------------------- #
# Frappe wrappers -- frappe is imported lazily so the pure core above stays    #
# importable without a bench.                                                  #
# --------------------------------------------------------------------------- #


def _recent_action_counts(student: str, since_days: int = 14) -> dict[str, int]:
	"""Per-action-type counts of a student's recent work items (kept for a future cooldown source)."""
	import frappe

	rows = frappe.get_all(
		"CRM Action Item",
		filters={
			"student": student,
			"creation": [">=", frappe.utils.add_days(frappe.utils.now_datetime(), -since_days)],
		},
		fields=["action_type", "count(name) as total"],
		group_by="action_type",
		limit_page_length=0,
		ignore_permissions=True,
	)
	return {row["action_type"]: int(row["total"] or 0) for row in rows if row.get("action_type")}


def _actor_roles(actor: str | None) -> set[str] | None:
	if not actor:
		return None
	import frappe

	return set(frappe.get_roles(actor))


def eligible_action_set_for_student(
	student: str, *, actor: str | None = None, now: datetime | None = None
) -> dict:
	"""Resolve the eligible action set for one student, failing closed on scope."""
	import frappe

	if not frappe.has_permission("CRM Student", "read", student, throw=False):
		frappe.throw("Student is outside the actor's scope.", frappe.PermissionError)

	evaluated_at = now or frappe.utils.now_datetime()
	catalog_rows = frappe.get_all(
		"CRM Action",
		fields=[
			"code",
			"display_name",
			"action_type",
			"purpose",
			"default_channel",
			"allowed_actors",
			"requires_approval",
			"auto_execute",
			"enabled",
			"definition_revision",
			"definition_digest",
			"effective_from",
			"effective_to",
		],
		limit_page_length=0,
	)
	for row in catalog_rows:
		row["category"] = row.get("action_type")

	# Frequency-cap inputs are deliberately omitted until a policy supplies real
	# per-code cooldown caps; `_recent_action_counts` alone would just be a
	# discarded query. `filter_eligible_actions` skips the cap when either side
	# is None.
	result = filter_eligible_actions(
		catalog_rows,
		now=evaluated_at,
		actor_roles=_actor_roles(actor),
	)
	revision = max((action["revision"] for action in result["actions"]), default=0)
	return {
		"revision": revision,
		"digest": eligible_set_digest(result["actions"]),
		"actions": result["actions"],
		"exclusions": result["exclusions"],
		"evaluated_at": evaluated_at,
	}


def get_active_decision_policy() -> dict:
	"""Return the single active ``default`` NBA Decision Policy, or fail closed."""
	import frappe

	rows = frappe.get_all(
		"CRM NBA Decision Policy",
		filters={"is_active": 1, "policy_key": "default"},
		fields=list(_ACTIVE_POLICY_FIELDS),
		limit_page_length=1,
	)
	if not rows:
		frappe.throw("No active NBA Decision Policy.", frappe.ValidationError)
	row = rows[0]
	return {
		"policy_revision": int(row.get("policy_revision") or 1),
		"policy_digest": row.get("policy_digest"),
		"top_n": int(row.get("top_n") or 3),
		"max_recommendations": int(row.get("max_recommendations") or 10),
		"min_score_threshold": float(row.get("min_score_threshold") or 0),
		"score_weights": validate_score_weights(row.get("score_weights")),
		"conflict_key_fields": json_string_list(row.get("conflict_key_fields")),
		"diversity_rule": row.get("diversity_rule") or "none",
	}
