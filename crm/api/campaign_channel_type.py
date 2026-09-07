"""Read API for campaign channel type lookup values."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from crm.api._pagination import paged_list

CHANNEL_TYPE_FIELDS = [
	"code",
	"display_name",
	"is_online",
	"is_offline",
	"enabled",
	"sort_order",
	"description",
]
SUPPORTED_MODES = frozenset({"ONLINE", "OFFLINE"})


def _is_enabled_only(value: bool | str) -> bool:
	return not (value is False or str(value).strip().lower() in {"0", "false", "no"})


def _with_modes(row: dict[str, Any]) -> dict[str, Any]:
	row["modes"] = [
		mode
		for mode, fieldname in (("ONLINE", "is_online"), ("OFFLINE", "is_offline"))
		if frappe.utils.cint(row.get(fieldname))
	]
	return row


@frappe.whitelist()
def list_campaign_channel_types(
	mode: str | None = None,
	search: str | None = None,
	enabled_only: bool | str = True,
	start: int | str = 0,
	page_length: int | str = 100,
) -> dict[str, Any]:
	"""List enabled campaign channel types available for the requested mode."""
	mode = (mode or "").strip().upper()
	if mode and mode not in SUPPORTED_MODES:
		frappe.throw(
			_("Mode must be ONLINE or OFFLINE."),
			frappe.ValidationError,
		)

	filters: dict[str, Any] = {}
	if _is_enabled_only(enabled_only):
		filters["enabled"] = 1
	if mode:
		filters["is_online" if mode == "ONLINE" else "is_offline"] = 1

	or_filters = None
	if search and search.strip():
		like = f"%{search.strip()}%"
		or_filters = [
			["code", "like", like],
			["display_name", "like", like],
			["description", "like", like],
		]

	result = paged_list(
		"CRM Campaign Channel Type",
		CHANNEL_TYPE_FIELDS,
		filters=filters,
		or_filters=or_filters,
		start=start,
		page_length=page_length,
		order_by="sort_order asc, code asc",
	)
	rows = [_with_modes(dict(row)) for row in result.pop("rows")]
	return {**result, "channel_types": rows}
