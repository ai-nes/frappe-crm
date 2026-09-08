"""Compatibility helpers for the unified HS Student identifier."""

from __future__ import annotations

import re
from typing import Any

from frappe.model.naming import make_autoname

LEAD_CODE_PATTERN = re.compile(r"^LD-(?P<year>\d{4})-(?P<sequence>\d{5,})$")
LEGACY_LEAD_NAME_PATTERN = re.compile(r"^ENR-(?P<year>\d{4})-(?P<sequence>\d+)$")
HS_CODE_PATTERN = re.compile(r"^HS-(?P<year>\d{4})-(?P<region>[A-Z0-9]+)-(?P<sequence>\d{6,})$", re.IGNORECASE)


def lead_code_from_name(name: Any) -> str | None:
	"""Return the unified HS ID for a Lead name."""
	hs_match = HS_CODE_PATTERN.fullmatch(str(name or "").strip())
	if hs_match:
		return (
			f"HS-{hs_match['year']}-{hs_match['region'].upper()}-"
			f"{hs_match['sequence'][-6:].zfill(6)}"
		)
	match = LEGACY_LEAD_NAME_PATTERN.fullmatch(str(name or "").strip())
	if not match:
		return None
	return f"HS-{match['year']}-HCM-{match['sequence'][-6:].zfill(6)}"


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
	"""Compatibility alias for callers that still allocate a Lead code."""
	return make_autoname(f"HS-{year}-HCM-.######")


def is_valid_lead_code(value: Any) -> bool:
	return bool(HS_CODE_PATTERN.fullmatch(str(value or "").strip()))
