"""Stable, non-PII identifiers for CRM Campaign records."""

from __future__ import annotations

import re
from typing import Any

from frappe.model.naming import make_autoname

CAMPAIGN_CODE_PATTERN = re.compile(r"^CAM-(?P<year>\d{4})-(?P<sequence>\d{5,})$")


def campaign_code_year(
	start_date: Any = None,
	creation: Any = None,
	fallback_year: int | str | None = None,
) -> str:
	"""Resolve the four-digit year used by the Campaign code series."""
	for value in (start_date, creation, fallback_year):
		match = re.search(r"(?<!\d)(\d{4})(?!\d)", str(value or ""))
		if match:
			return match.group(1)
	return "2000"


def next_campaign_code(year: str) -> str:
	"""Allocate the next five-digit sequence for a Campaign code."""
	return make_autoname(f"CAM-{year}-.#####")


def is_valid_campaign_code(value: Any) -> bool:
	return bool(CAMPAIGN_CODE_PATTERN.fullmatch(str(value or "").strip()))
