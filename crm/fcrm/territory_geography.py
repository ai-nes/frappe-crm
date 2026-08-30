"""Effective-date resolution for the canonical Territory geography map."""

from __future__ import annotations

from datetime import date
from typing import Any


def select_effective_assignment(rows: list[dict[str, Any]], as_of: str) -> dict[str, Any] | None:
	point = date.fromisoformat(str(as_of))
	active = [
		row
		for row in rows
		if row.get("status") == "Active"
		and date.fromisoformat(str(row["effective_from"])) <= point <= date.fromisoformat(str(row["effective_until"]))
	]
	if len(active) > 1:
		raise ValueError("overlapping active Territory geography assignments")
	return active[0] if active else None


def resolve_territory(*, geography_type: str, geography: str, as_of: str) -> str | None:
	import frappe

	rows = frappe.get_all(
		"CRM Territory Geography Assignment",
		filters={"geography_type": geography_type, "geography": geography, "status": "Active"},
		fields=["territory", "status", "effective_from", "effective_until"],
		limit_page_length=0,
	)
	assignment = select_effective_assignment(rows, as_of)
	return assignment.get("territory") if assignment else None
