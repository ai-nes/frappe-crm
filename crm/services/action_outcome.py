"""Bounded Workbench outcome vocabulary and Student progress projection."""

OUTCOME_CODES = frozenset({"success", "failed", "no_contact", "no_show"})
PROGRESS_CODES = frozenset({"POSITIVE_PROGRESS", "NO_PROGRESS", "NEGATIVE_PROGRESS", "UNKNOWN"})

_PROGRESS_BY_TYPE = {
	"CALL": {"success": "POSITIVE_PROGRESS", "failed": "NEGATIVE_PROGRESS", "no_contact": "NO_PROGRESS", "no_show": "NO_PROGRESS"},
	"EMAIL": {"success": "POSITIVE_PROGRESS", "failed": "NEGATIVE_PROGRESS", "no_contact": "NO_PROGRESS", "no_show": "NO_PROGRESS"},
}


def derive_progress(action_type: str, outcome_code: str) -> str:
	"""Return only the bounded semantic progress enum; never infer conversion."""
	return _PROGRESS_BY_TYPE.get(action_type, {}).get(outcome_code, "UNKNOWN")


def validate_outcome(outcome_code: str) -> str:
	if outcome_code not in OUTCOME_CODES:
		raise ValueError("Unsupported Workbench outcome code")
	return outcome_code
