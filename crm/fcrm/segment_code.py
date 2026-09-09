"""Stable identifiers for CRM Segment records."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import frappe

SEGMENT_CODE_PATTERN = re.compile(r"^SEG-(?P<date>\d{6})-(?P<short_id>[A-Z0-9]{6})$")
LEGACY_SEGMENT_CODE_PATTERN = re.compile(r"^SEG-(?P<date>\d{6})-(?P<username>.+)-(?P<short_id>[A-Z0-9]{6})$")
SEGMENT_DATE_PATTERN = re.compile(r"(?<!\d)(?P<year>\d{4})[-/]?(?P<month>\d{2})[-/]?(?P<day>\d{2})(?!\d)")


def segment_code_date(value: Any = None, fallback: Any = None) -> str:
	"""Resolve a creation date to the six-digit YYMMDD Segment code component."""
	for candidate in (value, fallback):
		if isinstance(candidate, (date, datetime)):
			return candidate.strftime("%y%m%d")
		match = SEGMENT_DATE_PATTERN.search(str(candidate or ""))
		if match:
			return f"{match['year'][-2:]}{match['month']}{match['day']}"
	return datetime.now().strftime("%y%m%d")


def generate_segment_code(username: Any, code_date: Any) -> str:
	"""Generate a short, collision-resistant Segment code.

	``username`` remains in the signature for compatibility with existing callers,
	but creator identity belongs in the owner/audit fields rather than the code.
	"""
	short_id = frappe.generate_hash(length=6).upper()
	return f"SEG-{segment_code_date(code_date)}-{short_id}"


def is_valid_segment_code(value: Any) -> bool:
	"""Return whether a value follows the Segment code contract."""
	code = str(value or "").strip()
	return bool(SEGMENT_CODE_PATTERN.fullmatch(code) or LEGACY_SEGMENT_CODE_PATTERN.fullmatch(code))
