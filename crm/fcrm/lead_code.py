"""Stable, non-PII identifiers for CRM Lead records."""

from __future__ import annotations

import re
from typing import Any

from frappe.model.naming import make_autoname

LEAD_CODE_PATTERN = re.compile(r"^LD-(?P<year>\d{4})-(?P<sequence>\d{5,})$")
LEGACY_LEAD_NAME_PATTERN = re.compile(r"^ENR-(?P<year>\d{4})-(?P<sequence>\d+)$")


def lead_code_from_name(name: Any) -> str | None:
	"""Convert the current ENR-style Lead identifier to the stable Lead code."""
	match = LEGACY_LEAD_NAME_PATTERN.fullmatch(str(name or "").strip())
	if not match:
		return None
	return f"LD-{match['year']}-{match['sequence'].zfill(5)}"


def lead_code_year(
	admission_year: Any = None,
	creation: Any = None,
	fallback_year: int | str | None = None,
) -> str:
	"""Resolve the four-digit year used by the Lead code series."""
	for value in (admission_year, creation, fallback_year):
		match = re.search(r"(?<!\d)(\d{4})(?!\d)", str(value or ""))
		if match:
			return match.group(1)
	return "2000"


def next_lead_code(year: str) -> str:
	"""Allocate the next five-digit sequence for a non-ENR legacy/custom name."""
	return make_autoname(f"LD-{year}-.#####")


def is_valid_lead_code(value: Any) -> bool:
	return bool(LEAD_CODE_PATTERN.fullmatch(str(value or "").strip()))
