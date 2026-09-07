"""Eligibility and decision-policy services for the NBA control plane.

Frappe is the sole authority for which actions a student may participate in:
the pure core here decides participation from catalog rows plus a few bounded
signals, and the AI evaluation service never re-interprets that verdict. The
Frappe wrappers gather the rows and fail closed on an out-of-scope student.
"""

from __future__ import annotations

import json
import math
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
		"NO_OPPORTUNITY_MAPPING",
		"LIFECYCLE_TERMINAL",
		"CHANNEL_NOT_ALLOWED",
		"RECIPIENT_AMBIGUOUS",
		"PARENT_AUTHORITY_MISSING",
	}
)

# Frappe is the owner of the action taxonomy.  This deliberately maps action
# *codes*, never categories: a new, internal, or destructive catalog action
# has no NBA opportunity until its business owner explicitly approves one.
_ACTION_OPPORTUNITIES: dict[str, tuple[str, ...]] = {
	**{
		code: ("ENGAGE_OR_REENGAGE",)
		for code in (
			"CALL", "SEND_ZALO", "SEND_EMAIL", "SEND_SMS", "VIDEO_CALL", "CALL_BACK",
			"SEND_MAJOR_INFO", "SEND_PROGRAM_INFO", "SEND_TUITION_INFO", "SEND_SCHOLARSHIP_INFO",
			"SEND_PROMOTION_INFO", "SEND_ADMISSION_INFO", "SEND_DORM_INFO", "SEND_CAREER_INFO",
			"SEND_BROCHURE", "SEND_MAJOR_VIDEO", "SEND_RELEVANT_FAQ", "INVITE_OPEN_DAY",
			"INVITE_CAMPUS_TOUR", "INVITE_WEBINAR", "INVITE_WORKSHOP", "INVITE_CLASS_EXPERIENCE",
			"INVITE_STEM_EVENT", "INVITE_MOCK_TEST", "BOOK_1ON1_CONSULTATION",
			"SEND_PERSONALIZED_CONTENT", "SEND_TESTIMONIAL", "FOLLOW_UP_SILENT_LEAD",
			"REENGAGE_LEAD", "ASK_DECISION_REASON", "SEND_OBJECTION_CONTENT", "SCHEDULE_LATER_FOLLOWUP",
		)
	},
	**{
		code: ("PROGRESS_APPLICATION",)
		for code in (
			"REMIND_APPLICATION", "GUIDE_NEXT_STEP", "ASSIST_APPLICATION_FEE",
			"CONFIRM_APPLICATION_RECEIVED", "ADVISE_MAJOR", "ADVISE_TUITION", "ADVISE_SCHOLARSHIP",
			"ADVISE_CAREER", "ADVISE_PARENT", "COMPARE_MAJORS", "COMPARE_CAMPUSES", "SEND_OFFER",
			"REMIND_ENROLLMENT_DEADLINE", "INVITE_CAMPUS_VISIT", "CONTACT_PARENT",
			"SEND_PARENT_TUITION", "SEND_PARENT_SCHOLARSHIP", "SEND_TRAINING_ROADMAP",
			"SEND_PARENT_CAREER_INFO", "INVITE_PARENT_EVENT", "BOOK_PARENT_CONSULTATION",
			"SEND_FINANCIAL_PLAN",
		)
	},
	**{
		code: ("COMPLETE_REQUIREMENT", "PROGRESS_APPLICATION")
		for code in (
			"REMIND_COMPLETE_APPLICATION", "REQUEST_MISSING_DOCUMENT", "CHECK_APPLICATION",
			"SEND_APPLICATION_CHECKLIST", "REMIND_APPLICATION_DEADLINE",
		)
	},
}


def action_opportunities(code: str | None, category: str | None = None) -> tuple[str, ...]:
	"""Return an explicitly governed opportunity mapping for one action code."""
	return _ACTION_OPPORTUNITIES.get(str(code or ""), ())

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
	"kernel_policy",
)

_KERNEL_POLICY_REQUIRED = (
	"revision",
	"score_threshold",
	"confidence_floor",
	"top_n_cap",
	"recommendation_ttl_seconds",
	"component_weights",
	"recent_contact_days",
	"cooling_contact_days",
	"contact_pressure_penalty",
	"redundancy_penalty",
	"diversity_group_penalty",
	"deadline_horizon_days",
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


def _parse_time_slots(value: object) -> list[str]:
	"""Normalise ``CRM Action.allowed_time_slots`` into a list of slot codes."""
	if isinstance(value, str):
		try:
			value = json.loads(value) if value else []
		except (TypeError, ValueError):
			return []
	if not isinstance(value, (list, tuple)):
		return []
	return [str(item) for item in value if str(item)]


def filter_eligible_actions(
	catalog_rows: Iterable[Mapping[str, object]],
	*,
	now: datetime,
	actor_roles: set[str] | None = None,
	recent_action_codes: Mapping[str, int] | None = None,
	cooldown_by_code: Mapping[str, int] | None = None,
	decision_context: Mapping[str, object] | None = None,
	parent_authority_channels: set[str] | None = None,
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
	decision_context = decision_context if isinstance(decision_context, Mapping) else None
	lifecycle = (decision_context or {}).get("lifecycle") or {}
	stage = str(lifecycle.get("stage") or "").casefold()
	terminal_lifecycle = stage in {"lost", "enrolled", "đã xác nhận", "closed", "withdrawn"}
	contactability = (decision_context or {}).get("contactability") or {}
	consent = contactability.get("consent") if isinstance(contactability, Mapping) else None
	channels = {
		str(channel).upper()
		for channel in (contactability.get("channels") or [])
		if isinstance(contactability, Mapping)
	}
	parent_channels = {str(channel).upper() for channel in (parent_authority_channels or set())}

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
		category = snapshot["category"] or action_category(code)
		opportunities = action_opportunities(code, category)
		if not opportunities:
			exclusions.append({"action": code, "reason": "NO_OPPORTUNITY_MAPPING"})
			continue
		if decision_context is not None and terminal_lifecycle:
			exclusions.append({"action": code, "reason": "LIFECYCLE_TERMINAL"})
			continue
		channel = str(snapshot["default_channel"] or "NONE").upper()
		# Parent-recipient consent is introduced with the dedicated authority
		# projection in phase 04. Until then, do not borrow the student's consent
		# to make a parent action executable.
		if decision_context is not None and category == "PARENT":
			exclusions.append({"action": code, "reason": "PARENT_AUTHORITY_MISSING"})
			continue
		if decision_context is not None and channel != "NONE":
			if isinstance(contactability, Mapping) and contactability.get("recipient_bound") is False:
				exclusions.append({"action": code, "reason": "RECIPIENT_AMBIGUOUS"})
				continue
			if consent is not True:
				exclusions.append({"action": code, "reason": "CONSENT_MISSING"})
				continue
			if channels and channel not in channels:
				exclusions.append({"action": code, "reason": "CHANNEL_NOT_ALLOWED"})
				continue
			if not channels:
				exclusions.append({"action": code, "reason": "CHANNEL_NOT_ALLOWED"})
				continue
		if decision_context is not None and bool(row.get("requires_parent_authority")):
			if channel == "NONE" or channel not in parent_channels:
				exclusions.append({"action": code, "reason": "PARENT_AUTHORITY_MISSING"})
				continue
		actions.append(
			{
				"code": code,
				"revision": _row_revision(row),
				"digest": _row_digest(row),
				"category": category,
				"default_channel": snapshot["default_channel"],
				"requires_parent_authority": bool(row.get("requires_parent_authority")),
				"academic_constraint": snapshot.get("academic_constraint") or {},
				"allowed_actors": allowed_actors,
				"purpose": snapshot["purpose"],
				"addresses_opportunities": list(opportunities),
				"allowed_time_slots": _parse_time_slots(row.get("allowed_time_slots")),
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


def kernel_policy_snapshot(row: Mapping[str, object]) -> dict:
	"""Parse the complete producer-owned kernel policy snapshot.

	The legacy ``score_weights`` field remains available for historical rows, but
	NBA evaluation refuses to use it as a hidden fallback.  A live policy must
	carry every kernel knob in ``kernel_policy`` and the caller binds its digest.
	"""
	raw = row.get("kernel_policy")
	if isinstance(raw, str):
		try:
			raw = json.loads(raw)
		except json.JSONDecodeError as exc:
			raise ValueError("kernel_policy must be valid JSON.") from exc
	if not isinstance(raw, Mapping):
		raise ValueError("kernel_policy is required for NBA evaluation.")
	missing = [key for key in _KERNEL_POLICY_REQUIRED if key not in raw]
	if missing:
		raise ValueError(f"kernel_policy is missing: {sorted(missing)}")
	unexpected = sorted(set(raw) - set(_KERNEL_POLICY_REQUIRED))
	if unexpected:
		raise ValueError(f"kernel_policy has unexpected fields: {unexpected}")
	weights = raw["component_weights"]
	if not isinstance(weights, Mapping) or set(weights) != {"opportunity_fit", "urgency", "effectiveness_index"}:
		raise ValueError("kernel_policy.component_weights must contain the three kernel weights.")
	if not isinstance(raw.get("revision"), str) or not raw["revision"]:
		raise ValueError("kernel_policy revision must be a non-empty string.")
	integer_fields = {
		"top_n_cap", "recommendation_ttl_seconds", "recent_contact_days",
		"cooling_contact_days", "deadline_horizon_days",
	}
	decimal_fields = {
		"score_threshold", "confidence_floor", "contact_pressure_penalty",
		"redundancy_penalty", "diversity_group_penalty",
	}
	if any(isinstance(raw[key], bool) or not isinstance(raw[key], int) for key in integer_fields):
		raise ValueError("kernel_policy integer values must be integers.")
	if any(isinstance(raw[key], bool) or not isinstance(raw[key], (int, float)) for key in decimal_fields):
		raise ValueError("kernel_policy decimal values must be numeric.")
	if any(isinstance(weights.get(key), bool) or not isinstance(weights.get(key), (int, float)) for key in weights):
		raise ValueError("kernel_policy weights must be numeric.")
	try:
		weights = {key: float(weights[key]) for key in sorted(weights)}
		if any(not math.isfinite(value) or value < 0 for value in weights.values()) or abs(sum(weights.values()) - 1.0) > 1e-9:
			raise ValueError
		snapshot = {
			"revision": raw["revision"],
			"score_threshold": float(raw["score_threshold"]),
			"confidence_floor": float(raw["confidence_floor"]),
			"top_n_cap": int(raw["top_n_cap"]),
			"recommendation_ttl_seconds": int(raw["recommendation_ttl_seconds"]),
			"component_weights": weights,
			"recent_contact_days": int(raw["recent_contact_days"]),
			"cooling_contact_days": int(raw["cooling_contact_days"]),
			"contact_pressure_penalty": float(raw["contact_pressure_penalty"]),
			"redundancy_penalty": float(raw["redundancy_penalty"]),
			"diversity_group_penalty": float(raw["diversity_group_penalty"]),
			"deadline_horizon_days": int(raw["deadline_horizon_days"]),
		}
		if snapshot["top_n_cap"] < 1 or snapshot["recommendation_ttl_seconds"] < 1:
			raise ValueError
		if any(snapshot[key] < 0 for key in ("recent_contact_days", "cooling_contact_days", "deadline_horizon_days")):
			raise ValueError
		if any(
			not math.isfinite(snapshot[key]) or not 0.0 <= snapshot[key] <= 1.0
			for key in (
				"score_threshold", "confidence_floor", "contact_pressure_penalty",
				"redundancy_penalty", "diversity_group_penalty",
			)
		):
			raise ValueError
		return snapshot
	except (TypeError, ValueError, OverflowError) as exc:
		raise ValueError("kernel_policy contains invalid numeric values.") from exc


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


def _parent_authority_wire_channels(student: str, at: datetime) -> set[str]:
	"""Resolve verified parent authority to the NBA channel vocabulary."""
	import frappe

	rows = frappe.get_all(
		"CRM Parent Contact Authority",
		filters={
			"student": student,
			"relationship_verified": 1,
			"revoked_at": ["is", "not set"],
			"effective_at": ["<=", at],
		},
		fields=["contact", "allowed_channels", "expires_at", "lawful_basis"],
		limit_page_length=50,
		ignore_permissions=True,
	)
	valid_rows = []
	result: set[str] = set()
	aliases = {
		"call": "CALL",
		"phone": "CALL",
		"voice": "CALL",
		"email": "EMAIL",
		"e-mail": "EMAIL",
		"zalo": "MESSAGE",
		"message": "MESSAGE",
		"sms": "MESSAGE",
	}
	for row in rows:
		if row.get("expires_at") and row["expires_at"] < at:
			continue
		if not row.get("lawful_basis"):
			continue
		valid_rows.append(row)
	# A channel union across different parent contacts is not an executable
	# recipient binding.  Fail closed unless one unique authority recipient is
	# available; the dispatch path can then resolve the same contact again.
	if not valid_rows or len({str(row.get("contact") or "") for row in valid_rows}) != 1:
		return set()
	for row in valid_rows:
		values = row.get("allowed_channels") or []
		values = frappe.parse_json(values) if isinstance(values, str) else values
		if not isinstance(values, (list, tuple)):
			continue
		result.update(aliases.get(str(value).strip().casefold(), str(value).upper()) for value in values)
	return {value for value in result if value in {"CALL", "EMAIL", "MESSAGE"}}


def eligible_action_set_for_student(
	student: str,
	*,
	actor: str | None = None,
	now: datetime | None = None,
	service_authorized: bool = False,
	decision_context: Mapping[str, object] | None = None,
) -> dict:
	"""Resolve the eligible action set for one student, failing closed on scope.

	``service_authorized=True`` must only be passed by a caller that already
	verified the current request is the crm-agents service identity (see
	``_projection``'s docstring in ``student_decision_context.py`` for the
	same pattern) -- it is never inferred from ``actor``.
	"""
	import frappe

	if not service_authorized and not frappe.has_permission("CRM Lead", "read", student, throw=False):
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
			"requires_parent_authority",
			"academic_constraint",
			"allowed_time_slots",
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
		decision_context=decision_context,
		parent_authority_channels=(
			_parent_authority_wire_channels(student, evaluated_at)
			if decision_context is not None
			else None
		),
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
	try:
		kernel = kernel_policy_snapshot(row)
	except ValueError as exc:
		frappe.throw(str(exc), frappe.ValidationError)
	kernel_digest = canonical_digest(kernel)
	if str(row.get("policy_digest") or "") != kernel_digest:
		frappe.throw("Active NBA Decision Policy digest does not bind kernel_policy.", frappe.ValidationError)
	return {
		"policy_revision": int(row.get("policy_revision") or 1),
		"policy_digest": row.get("policy_digest"),
		"top_n": int(row.get("top_n") or 3),
		"max_recommendations": int(row.get("max_recommendations") or 10),
		"min_score_threshold": float(row.get("min_score_threshold") or 0),
		"score_weights": validate_score_weights(row.get("score_weights")),
		"conflict_key_fields": json_string_list(row.get("conflict_key_fields")),
		"diversity_rule": row.get("diversity_rule") or "none",
		"decision_policy": kernel,
		"policy_digest": kernel_digest,
	}


def ensure_default_decision_policy() -> bool:
	"""Create or activate the canonical default policy for a fresh local site."""
	import frappe

	if frappe.db.exists("CRM NBA Decision Policy", {"policy_key": "default", "is_active": 1}):
		return False

	frappe.db.set_value("CRM NBA Decision Policy", {"is_active": 1}, "is_active", 0)
	policy = frappe.db.get_value("CRM NBA Decision Policy", {"policy_key": "default"}, "name")
	if policy:
		frappe.db.set_value("CRM NBA Decision Policy", policy, "is_active", 1)
		return True

	frappe.get_doc(
		{
			"doctype": "CRM NBA Decision Policy",
			"policy_key": "default",
			"policy_revision": 1,
			"is_active": 1,
			"top_n": 3,
			"max_recommendations": 10,
			"min_score_threshold": 0,
			"score_weights": json.dumps({"confidence": 0.5, "impact": 0.5}, sort_keys=True),
			"kernel_policy": json.dumps(
				{
					"revision": "nba-decision-policy-r1",
					"score_threshold": 0.35,
					"confidence_floor": 0.45,
					"top_n_cap": 3,
					"recommendation_ttl_seconds": 604800,
					"component_weights": {
						"opportunity_fit": 0.45,
						"urgency": 0.25,
						"effectiveness_index": 0.30,
					},
					"recent_contact_days": 2,
					"cooling_contact_days": 5,
					"contact_pressure_penalty": 0.15,
					"redundancy_penalty": 0.10,
					"diversity_group_penalty": 0.05,
					"deadline_horizon_days": 30,
				},
				sort_keys=True,
			),
			"conflict_key_fields": json.dumps(["student", "action"]),
			"diversity_rule": "none",
		}
	).insert(ignore_permissions=True)
	return True
