"""Validation for score-history contributor rows."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence

import frappe

_CATEGORIES = frozenset({"Fit", "Engagement", "Intent", "Time Decay", "Negative"})
_TOKEN = re.compile(r"^[A-Za-z0-9_.\- ]{1,64}$")
_FIELDS = frozenset({"category", "rule_id", "signal", "score", "reason"})
_MAX_ROWS = 60
_MAX_REASON_CHARS = 240


def _invalid(message: str):
	frappe.throw(message, frappe.ValidationError)


def validate_contributors(contributors: Sequence[Mapping] | None) -> list[dict]:
	"""Return normalized contributor rows or raise a Frappe ValidationError."""
	if contributors is None:
		return []
	if not isinstance(contributors, (list, tuple)):
		_invalid("Score contributors must be a list.")
	if len(contributors) > _MAX_ROWS:
		_invalid(f"Score contributors cannot contain more than {_MAX_ROWS} rows.")
	validated: list[dict] = []
	for index, contributor in enumerate(contributors):
		if not isinstance(contributor, Mapping) or set(contributor) != _FIELDS:
			_invalid(f"Score contributor {index} has an unsupported shape.")
		category = str(contributor.get("category") or "").strip()
		if category not in _CATEGORIES:
			_invalid(f"Score contributor {index} has an invalid category.")
		row: dict = {"category": category}
		for field in ("rule_id", "signal"):
			value = contributor.get(field)
			if not isinstance(value, str) or not _TOKEN.fullmatch(value.strip()):
				_invalid(f"Score contributor {index} has an invalid {field}.")
			row[field] = value.strip()
		try:
			score = float(contributor.get("score"))
		except (TypeError, ValueError):
			_invalid(f"Score contributor {index} has an invalid score.")
		if not math.isfinite(score):
			_invalid(f"Score contributor {index} has an invalid score.")
		row["score"] = score
		reason = contributor.get("reason")
		if not isinstance(reason, str):
			_invalid(f"Score contributor {index} has an invalid reason.")
		reason = reason.strip()
		if len(reason) > _MAX_REASON_CHARS:
			_invalid(f"Score contributor {index} reason exceeds {_MAX_REASON_CHARS} characters.")
		row["reason"] = reason
		validated.append(row)
	return validated
