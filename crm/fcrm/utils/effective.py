"""Small helpers for effective-dated CRM assignment records."""

from __future__ import annotations

from datetime import date

from frappe.utils import getdate, today


def is_effective(row, at: date | None = None) -> bool:
	"""Return whether an effective-dated row covers ``at`` (inclusive)."""
	at = getdate(at or today())
	start = row.get("effective_from")
	end = row.get("effective_until")
	return (not start or getdate(start) <= at) and (not end or getdate(end) >= at)


def periods_overlap(left, right) -> bool:
	"""Return whether two inclusive effective periods overlap."""
	left_start = getdate(left.get("effective_from")) if left.get("effective_from") else date.min
	left_end = getdate(left.get("effective_until")) if left.get("effective_until") else date.max
	right_start = getdate(right.get("effective_from")) if right.get("effective_from") else date.min
	right_end = getdate(right.get("effective_until")) if right.get("effective_until") else date.max
	return left_start <= right_end and right_start <= left_end
