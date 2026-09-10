"""Outcome vocabulary, per-action-category validity, and Decision Effect derivation.

An outcome recorded on a completed ``CRM Action Item`` is only meaningful when
interpreted through the category of the action that produced it (a CONTACT
call and an APPLICATION reminder don't share the same outcome vocabulary, and
even a shared code like ``NOT_INTERESTED`` means something different depending
on domain). ``derive_decision_effects`` is the single source both the write
path (validation) and the read path (NBA context folding) use, so the two
can never drift apart.

Mapping granularity is per action *category* (the 8 values in
``action_type_catalog.ACTION_TYPE_CATALOG``), not per individual action code,
to avoid hand-authoring near-duplicate tables for 79 codes.
``ACTION_EFFECT_OVERRIDES`` is the place for an action whose outcome
vocabulary must diverge from its category's default -- e.g. an internal
handoff action that stays in a contact-style category for routing purposes
but never represents an actual student touch.
"""
from __future__ import annotations

from typing import NamedTuple

from crm.fcrm.action_type_catalog import action_category


class DecisionEffect(NamedTuple):
	dimension: str
	value: str


# Every dimension a decision effect can target, with the reducer the fold
# step (crm/api/nba_evaluation.py) must use. Declared here, not inferred, so
# adding a dimension always means deciding how it folds.
#
# "latest" persists across unrelated intervening outcomes (a "not interested"
# from 5 actions ago is still meaningful even if nothing since touched
# interest). "latest_or_reset" does not persist: it reflects only the single
# most recent completed action's outcome -- if that action didn't touch the
# dimension, the dimension is unknown/none, regardless of older history.
# follow_up uses this: a stale "please call back" from several actions ago
# must not stay sticky forever once newer, unrelated work has happened since.
#
# decision_status has per-value lifecycle semantics instead of one uniform
# rule (see DECISION_STATUS_REOPEN_TRIGGERS below): "pending" is transient
# (same rule as latest_or_reset -- only the single most recent completed
# action can hold it); "not_ready" is semi-sticky (persists like "latest"
# across unrelated outcomes, but is cleared by a REENGAGED or
# INTEREST_CONFIRMED outcome, or by any newer decision_status outcome);
# "lost" is sticky/terminal (persists like "latest", cleared only by a
# REENGAGED outcome -- an explicit reopen/winback signal, not just any
# renewed interest).
DIMENSION_REDUCERS: dict[str, str] = {
	"interest_disposition": "latest",
	"application_assessment": "latest",
	"follow_up": "latest_or_reset",
	"contact_attempt_signal": "consecutive_since_reset",
	"decision_status": "decision_status_lifecycle",
	"enrollment_assessment": "latest",
	"parent_disposition": "latest",
}

# Outcome codes that reopen a currently-held decision_status value, keyed by
# that value. Consulted by the fold step (crm.api.nba_evaluation) against the
# raw outcome_code of each row scanned more recently than the row that set
# the value -- see DIMENSION_REDUCERS above for the per-value rationale.
DECISION_STATUS_REOPEN_TRIGGERS: dict[str, frozenset[str]] = {
	"not_ready": frozenset({"REENGAGED", "INTEREST_CONFIRMED"}),
	"lost": frozenset({"REENGAGED"}),
}

# contact_attempt_signal is the only consecutive_since_reset dimension today;
# "succeeded" is the value that resets the streak.
CONTACT_ATTEMPT_RESET_VALUE = "succeeded"
CONTACT_ATTEMPT_FAILURE_VALUE = "failed"

_CONTACT_SUCCEEDS = (DecisionEffect("contact_attempt_signal", CONTACT_ATTEMPT_RESET_VALUE),)
_CONTACT_FAILS = (DecisionEffect("contact_attempt_signal", CONTACT_ATTEMPT_FAILURE_VALUE),)

# category -> outcome_code -> effects. The outcome_code keys of a category are
# exactly its allowed vocabulary -- an outcome not listed here is invalid for
# that category. An empty tuple is a legitimately allowed outcome with no
# student-state effect (e.g. an INTERNAL housekeeping action).
CATEGORY_OUTCOME_EFFECTS: dict[str, dict[str, tuple[DecisionEffect, ...]]] = {
	"CONTACT": {
		"NO_RESPONSE": _CONTACT_FAILS,
		"CALL_BACK_LATER": (DecisionEffect("follow_up", "requested"), *_CONTACT_SUCCEEDS),
		"INTEREST_CONFIRMED": (DecisionEffect("interest_disposition", "confirmed"), *_CONTACT_SUCCEEDS),
		"INTEREST_INCREASED": (DecisionEffect("interest_disposition", "increased"), *_CONTACT_SUCCEEDS),
		"NEEDS_MORE_INFORMATION": (DecisionEffect("interest_disposition", "needs_info"), *_CONTACT_SUCCEEDS),
		"DECISION_PENDING": (DecisionEffect("decision_status", "pending"), *_CONTACT_SUCCEEDS),
		"NOT_INTERESTED": (DecisionEffect("interest_disposition", "not_interested"), *_CONTACT_SUCCEEDS),
	},
	"INFORMATION": {
		"INFORMATION_DELIVERED": _CONTACT_SUCCEEDS,
		"NEEDS_MORE_INFORMATION": (DecisionEffect("interest_disposition", "needs_info"),),
		"INTEREST_CONFIRMED": (DecisionEffect("interest_disposition", "confirmed"),),
		"INTEREST_INCREASED": (DecisionEffect("interest_disposition", "increased"),),
		"DECISION_PENDING": (DecisionEffect("decision_status", "pending"),),
		"NOT_INTERESTED": (DecisionEffect("interest_disposition", "not_interested"),),
	},
	"ENGAGEMENT": {
		"INVITATION_ACCEPTED": _CONTACT_SUCCEEDS,
		"INVITATION_DECLINED": _CONTACT_SUCCEEDS,
		"ATTENDED": (DecisionEffect("interest_disposition", "increased"), *_CONTACT_SUCCEEDS),
		# A no-show is an engagement outcome (didn't attend an invited event),
		# not a failed contact attempt -- the invite itself was delivered and
		# acknowledged, so it must not count against contact_attempt_signal.
		"NO_SHOW": (),
		"INTEREST_INCREASED": (DecisionEffect("interest_disposition", "increased"), *_CONTACT_SUCCEEDS),
		"DECISION_PENDING": (DecisionEffect("decision_status", "pending"), *_CONTACT_SUCCEEDS),
		"NOT_INTERESTED": (DecisionEffect("interest_disposition", "not_interested"), *_CONTACT_SUCCEEDS),
	},
	"APPLICATION": {
		"APPLICATION_STARTED": (DecisionEffect("application_assessment", "started"),),
		"APPLICATION_IN_PROGRESS": (DecisionEffect("application_assessment", "in_progress"),),
		"APPLICATION_BLOCKED": (DecisionEffect("application_assessment", "blocked"),),
		"NEEDS_MORE_INFORMATION": (DecisionEffect("application_assessment", "needs_document"),),
		"APPLICATION_COMPLETED": (DecisionEffect("application_assessment", "completed_confirmed"),),
	},
	"CONVERSION": {
		"INTEREST_CONFIRMED": (DecisionEffect("interest_disposition", "confirmed"),),
		"INTEREST_INCREASED": (DecisionEffect("interest_disposition", "increased"),),
		"NEEDS_MORE_INFORMATION": (DecisionEffect("interest_disposition", "needs_info"),),
		"DECISION_PENDING": (DecisionEffect("decision_status", "pending"),),
		"NOT_INTERESTED": (DecisionEffect("interest_disposition", "not_interested"),),
		"ENROLLMENT_CONFIRMED": (DecisionEffect("enrollment_assessment", "confirmed"),),
	},
	"PARENT": {
		"PARENT_SUPPORTIVE": (DecisionEffect("parent_disposition", "supportive"),),
		"PARENT_UNDECIDED": (DecisionEffect("parent_disposition", "undecided"),),
		"PARENT_NOT_SUPPORTIVE": (DecisionEffect("parent_disposition", "not_supportive"),),
		"NEEDS_MORE_INFORMATION": (DecisionEffect("parent_disposition", "needs_info"),),
		"CALL_BACK_LATER": (DecisionEffect("follow_up", "requested"), *_CONTACT_SUCCEEDS),
	},
	"RECOVERY": {
		"NO_RESPONSE": _CONTACT_FAILS,
		"CALL_BACK_LATER": (DecisionEffect("follow_up", "requested"), *_CONTACT_SUCCEEDS),
		"REENGAGED": (DecisionEffect("interest_disposition", "increased"), *_CONTACT_SUCCEEDS),
		# Not a flavor of interest -- "not ready yet" is a recovery decision
		# state, distinct from the student needing more information.
		"NOT_READY": (DecisionEffect("decision_status", "not_ready"), *_CONTACT_SUCCEEDS),
		"DECISION_PENDING": (DecisionEffect("decision_status", "pending"), *_CONTACT_SUCCEEDS),
		"NOT_INTERESTED": (DecisionEffect("interest_disposition", "not_interested"), *_CONTACT_SUCCEEDS),
		"LOST_CONFIRMED": (
			DecisionEffect("interest_disposition", "not_interested"),
			DecisionEffect("decision_status", "lost"),
			*_CONTACT_SUCCEEDS,
		),
	},
	"INTERNAL": {
		"COMPLETED": (),
		"FAILED": (),
		"CANCELLED": (),
	},
}

# Per action-code overrides, keyed by the CRM Action ``code`` (e.g. "CALL"),
# checked before the category default. These four actions stay in a
# contact-style category for routing/eligibility purposes, but represent an
# internal handoff, not an actual student touch -- so they get the INTERNAL
# vocabulary instead of their category's contact/interest vocabulary.
_HANDOFF_PROFILE: dict[str, tuple[DecisionEffect, ...]] = {
	"COMPLETED": (),
	"FAILED": (),
	"CANCELLED": (),
}
ACTION_EFFECT_OVERRIDES: dict[str, dict[str, tuple[DecisionEffect, ...]]] = {
	"REASSIGN_ADVISOR": dict(_HANDOFF_PROFILE),
	"ESCALATE_SUPERVISOR": dict(_HANDOFF_PROFILE),
	"ESCALATE_HIGH_INTENT": dict(_HANDOFF_PROFILE),
	"ESCALATE_TO_SENIOR": dict(_HANDOFF_PROFILE),
}

OUTCOME_CODES = frozenset(
	code for outcomes in CATEGORY_OUTCOME_EFFECTS.values() for code in outcomes
)

# Vietnamese display name Sale sees and picks from -- Sale interacts through
# this label, never the raw outcome_code. One name per code: the same code
# means the same thing across every category it appears in.
OUTCOME_DISPLAY_NAMES: dict[str, str] = {
	"NO_RESPONSE": "Không phản hồi",
	"CALL_BACK_LATER": "Hẹn liên hệ lại",
	"INTEREST_CONFIRMED": "Xác nhận còn quan tâm",
	"INTEREST_INCREASED": "Mức độ quan tâm tăng",
	"NEEDS_MORE_INFORMATION": "Cần thêm thông tin",
	"DECISION_PENDING": "Đang cân nhắc",
	"NOT_INTERESTED": "Không còn quan tâm",
	"INFORMATION_DELIVERED": "Đã cung cấp thông tin",
	"INVITATION_ACCEPTED": "Đồng ý tham gia",
	"INVITATION_DECLINED": "Từ chối tham gia",
	"ATTENDED": "Đã tham gia",
	"NO_SHOW": "Không tham gia",
	"APPLICATION_STARTED": "Đã bắt đầu hồ sơ",
	"APPLICATION_IN_PROGRESS": "Đang hoàn thiện hồ sơ",
	"APPLICATION_BLOCKED": "Hồ sơ đang vướng",
	"APPLICATION_COMPLETED": "Đã hoàn tất hồ sơ",
	"ENROLLMENT_CONFIRMED": "Đã xác nhận nhập học",
	"PARENT_SUPPORTIVE": "Phụ huynh đồng thuận",
	"PARENT_UNDECIDED": "Phụ huynh đang cân nhắc",
	"PARENT_NOT_SUPPORTIVE": "Phụ huynh chưa đồng thuận",
	"REENGAGED": "Đã quan tâm trở lại",
	"NOT_READY": "Chưa sẵn sàng",
	"LOST_CONFIRMED": "Xác nhận không tiếp tục",
	"COMPLETED": "Hoàn tất",
	"FAILED": "Không hoàn thành",
	"CANCELLED": "Đã hủy",
}

# Legacy bounded progress vocabulary, retained as audit/analytics metadata
# only. NBA reads Decision Effects (below), never this.
PROGRESS_CODES = frozenset({"POSITIVE_PROGRESS", "NO_PROGRESS", "NEGATIVE_PROGRESS", "UNKNOWN"})

_POSITIVE_DIMENSION_VALUES = {
	("interest_disposition", "increased"),
	("interest_disposition", "confirmed"),
	("application_assessment", "started"),
	("application_assessment", "completed_confirmed"),
	("contact_attempt_signal", "succeeded"),
	("enrollment_assessment", "confirmed"),
	("parent_disposition", "supportive"),
}
_NEGATIVE_DIMENSION_VALUES = {
	("interest_disposition", "not_interested"),
	("application_assessment", "blocked"),
	("contact_attempt_signal", "failed"),
	("parent_disposition", "not_supportive"),
	("decision_status", "lost"),
}


def _outcomes_for(action_code: str | None) -> dict[str, tuple[DecisionEffect, ...]]:
	category = action_category(action_code) or ""
	return CATEGORY_OUTCOME_EFFECTS.get(category, {})


def allowed_outcomes(action_code: str | None) -> frozenset[str]:
	"""Outcome codes valid for this action's category (or its own override)."""
	override = ACTION_EFFECT_OVERRIDES.get(action_code or "")
	if override is not None:
		return frozenset(override)
	return frozenset(_outcomes_for(action_code))


def validate_outcome(outcome_code: str, action_code: str | None = None) -> str:
	"""Validate an outcome_code, scoped to ``action_code``'s category when given.

	Kept backward-callable with just ``outcome_code`` (checks the global
	vocabulary) for existing unscoped callers; new callers should always pass
	``action_code`` so the check is action-appropriate, not just globally
	spelled correctly.
	"""
	if action_code is not None:
		if outcome_code not in allowed_outcomes(action_code):
			raise ValueError(f"Outcome '{outcome_code}' is not valid for action '{action_code}'")
		return outcome_code
	if outcome_code not in OUTCOME_CODES:
		raise ValueError("Unsupported outcome code")
	return outcome_code


def derive_decision_effects(action_code: str | None, outcome_code: str | None) -> tuple[DecisionEffect, ...]:
	"""0..N typed Decision Effects for a completed action's outcome.

	Pure lookup, no Frappe I/O -- safe to call from both the write-path
	validator and the read-path NBA context builder.
	"""
	if not outcome_code:
		return ()
	override = ACTION_EFFECT_OVERRIDES.get(action_code or "")
	table = override if override is not None else _outcomes_for(action_code)
	return table.get(outcome_code, ())


def derive_progress(action_type: str, outcome_code: str) -> str:
	"""Legacy bounded progress signal, audit/analytics only -- never fed to NBA.

	Derived from the same Decision Effects so it can't drift from them:
	POSITIVE_PROGRESS/NEGATIVE_PROGRESS if any effect lands in the respective
	set above, NO_PROGRESS if effects exist but are neutral, UNKNOWN if the
	action/outcome pair has no defined effect at all.
	"""
	effects = derive_decision_effects(action_type, outcome_code)
	if not effects:
		return "UNKNOWN"
	if any((e.dimension, e.value) in _POSITIVE_DIMENSION_VALUES for e in effects):
		return "POSITIVE_PROGRESS"
	if any((e.dimension, e.value) in _NEGATIVE_DIMENSION_VALUES for e in effects):
		return "NEGATIVE_PROGRESS"
	return "NO_PROGRESS"
