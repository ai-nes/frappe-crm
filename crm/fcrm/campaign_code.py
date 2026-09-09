"""Stable, non-PII identifiers for CRM Campaign records."""

from __future__ import annotations

import re
import secrets
from datetime import date, datetime
from typing import Any

from frappe.model.naming import make_autoname

CAMPAIGN_CODE_PATTERN = re.compile(
	r"^CMP-(?P<campus_code>[A-Z0-9]+(?:-[A-Z0-9]+)*)-(?P<date>\d{6})-"
	r"(?P<token>[A-HJ-NP-Z2-9]{4})$"
)
LEGACY_CAMPAIGN_CODE_PATTERN = re.compile(r"^CAM-(?P<year>\d{4})-(?P<sequence>\d{5,})$")
CAMPUS_CODE_PATTERN = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$")
CAMPAIGN_DATE_PATTERN = re.compile(r"(?<!\d)(?P<year>\d{4})[-/]?(?P<month>\d{2})[-/]?(?P<day>\d{2})(?!\d)")
CAMPAIGN_CODE_TOKEN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CAMPAIGN_CODE_TOKEN_LENGTH = 4


def normalize_campus_code(value: Any) -> str:
	"""Return a canonical Campus Code suitable for use in a Campaign code."""
	code = str(value or "").strip().upper()
	if not CAMPUS_CODE_PATTERN.fullmatch(code):
		raise ValueError("Campus Code must contain only letters, numbers, and hyphens.")
	return code


def campaign_code_year(
	start_date: Any = None,
	creation: Any = None,
	fallback_year: int | str | None = None,
) -> str:
	"""Resolve the four-digit year used by the legacy Campaign code series."""
	for value in (start_date, creation, fallback_year):
		match = re.search(r"(?<!\d)(\d{4})(?!\d)", str(value or ""))
		if match:
			return match.group(1)
	return "2000"


def campaign_code_date(value: Any = None, fallback: Any = None) -> str:
	"""Resolve a creation date to the six-digit YYMMDD Campaign code component."""
	for candidate in (value, fallback):
		if isinstance(candidate, (date, datetime)):
			return candidate.strftime("%y%m%d")
		match = CAMPAIGN_DATE_PATTERN.search(str(candidate or ""))
		if match:
			return f"{match['year'][-2:]}{match['month']}{match['day']}"
	return datetime.now().strftime("%y%m%d")


def _campaign_code_token() -> str:
	return "".join(secrets.choice(CAMPAIGN_CODE_TOKEN_ALPHABET) for _ in range(CAMPAIGN_CODE_TOKEN_LENGTH))


def next_campaign_code(campus_code: str, code_date: Any | None = None) -> str:
	"""Generate a current Campus/date code or a legacy year-only code."""
	if code_date is None:
		return make_autoname(f"CAM-{campus_code}-.#####")
	return (
		f"CMP-{normalize_campus_code(campus_code)}-{campaign_code_date(code_date)}-{_campaign_code_token()}"
	)


def is_valid_campaign_code(value: Any) -> bool:
	code = str(value or "").strip()
	return bool(CAMPAIGN_CODE_PATTERN.fullmatch(code) or LEGACY_CAMPAIGN_CODE_PATTERN.fullmatch(code))
