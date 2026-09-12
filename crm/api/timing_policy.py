"""Read APIs for the CRM Timing Policy catalogue."""

from __future__ import annotations

from typing import Any

import frappe

from crm.api._pagination import paged_list, parse_pagination

FIELDS = [
	"name",
	"trigger_type",
	"trigger_event",
	"delay_value",
	"delay_unit",
	"time_slot",
	"allowed_start_time",
	"allowed_end_time",
	"deadline_type",
	"deadline_offset",
	"recurrence_type",
	"recurrence_interval",
	"stop_condition",
	"optimization_enabled",
	"optimization_objective",
	"modified",
]


def _require_admin() -> None:
	if frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles(frappe.session.user):
		return
	frappe.throw("Only System Managers may view timing policies.", frappe.PermissionError)


@frappe.whitelist()
def list_timing_policies(
	start: int | str = 0,
	page_length: int | str = 20,
	search: str | None = None,
	trigger_type: str | None = None,
) -> dict[str, Any]:
	"""Return a permission-scoped page of timing policies."""
	_require_admin()
	start, page_length = parse_pagination(start, page_length)
	filters = {}
	trigger_value = str(trigger_type or "").strip()
	if trigger_value and trigger_value != "all":
		filters["trigger_type"] = trigger_value
	search_value = str(search or "").strip()
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [[fieldname, "like", like] for fieldname in ("name", "trigger_type", "trigger_event")]

	result = paged_list(
		"CRM Timing Policy",
		FIELDS,
		filters=filters,
		or_filters=or_filters,
		start=start,
		page_length=page_length,
		order_by="modified desc, name asc",
	)
	rows = result.pop("rows")
	for row in rows:
		# Timing Policy currently uses hash naming rather than a separate policy_key
		# field. Keep the frontend display key stable without changing the DocType.
		row["policy_key"] = row.get("policy_key") or row.get("name")
	return {"policies": rows, **result}
