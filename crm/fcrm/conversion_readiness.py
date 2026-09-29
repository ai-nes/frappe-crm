"""Pure qualification rules for Lead -> Student conversion.

``major`` (Ngành quan tâm) is intake metadata, not a conversion gate: it is
optional and must never block a Lead from being processed, routed, or
converted into a Student.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

REQUIRED_CONVERSION_FIELDS = (
	("phone", "missing_phone"),
	("province", "missing_province"),
	("high_school", "missing_high_school"),
)


def _value(record: Any, fieldname: str) -> Any:
	if isinstance(record, Mapping):
		return record.get(fieldname)
	return getattr(record, fieldname, None)


def conversion_blockers(lead: Any) -> list[str]:
	"""Return deterministic machine-readable blockers for one Lead."""
	return [
		blocker
		for fieldname, blocker in REQUIRED_CONVERSION_FIELDS
		if not str(_value(lead, fieldname) or "").strip()
	]


def is_conversion_ready(lead: Any) -> bool:
	return not conversion_blockers(lead)


def conversion_readiness(lead: Any) -> dict[str, Any]:
	"""Return the stable readiness projection used by APIs and DocType hooks."""
	blockers = conversion_blockers(lead)
	return {
		"ready": not blockers,
		"status": "Ready" if not blockers else "Not Ready",
		"blockers": blockers,
	}


def is_lead_converted(lead: Any) -> bool:
	"""Return whether a Lead already owns a conversion relationship.

	The direct ``student`` link is retained for legacy rows, while new conversion
	commands stamp ``converted_student`` and ``converted_at``. Any of these
	projections is enough to protect the Student and immutable conversion history
	from Lead deletion.
	"""
	return any(
		_value(lead, fieldname)
		for fieldname in ("converted_student", "converted_at", "student")
	)
