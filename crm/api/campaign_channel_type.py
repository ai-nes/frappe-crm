"""Read API for campaign channel type lookup values."""

from __future__ import annotations

import re
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
CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,49}$")


def _is_enabled_only(value: bool | str) -> bool:
	return not (value is False or str(value).strip().lower() in {"0", "false", "no"})


def _with_modes(row: dict[str, Any]) -> dict[str, Any]:
	row["modes"] = [
		mode
		for mode, fieldname in (("ONLINE", "is_online"), ("OFFLINE", "is_offline"))
		if frappe.utils.cint(row.get(fieldname))
	]
	return row


def _require_authentication() -> None:
	if getattr(getattr(frappe, "session", None), "user", "Guest") == "Guest":
		frappe.throw(_("Authentication is required."), frappe.AuthenticationError)


def _parse_data(data: dict[str, Any] | str | None) -> dict[str, Any]:
	if isinstance(data, str):
		try:
			data = frappe.parse_json(data)
		except (TypeError, ValueError):
			data = None
	if not isinstance(data, dict):
		frappe.throw(_("Channel type data must be an object."), frappe.ValidationError)
	return data


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
	allowed = {"code", "display_name", "is_online", "is_offline", "enabled", "sort_order", "description"}
	unknown = set(data) - allowed
	if unknown:
		frappe.throw(
			_("Unsupported channel type fields: {0}.").format(", ".join(sorted(unknown))),
			frappe.ValidationError,
		)
	values = {key: data[key] for key in allowed if key in data}
	if "code" in values:
		values["code"] = str(values["code"] or "").strip().upper()
		if not CODE_PATTERN.fullmatch(values["code"]):
			frappe.throw(
				_("Code must use 2-50 uppercase letters, digits and underscores."), frappe.ValidationError
			)
	for fieldname in ("is_online", "is_offline", "enabled"):
		if fieldname in values:
			values[fieldname] = frappe.utils.cint(values[fieldname])
	if "sort_order" in values:
		values["sort_order"] = frappe.utils.cint(values["sort_order"])
	return values


def _payload(doc: Any) -> dict[str, Any]:
	return _with_modes({field: doc.get(field) for field in CHANNEL_TYPE_FIELDS})


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


@frappe.whitelist(methods=["POST"])
def create_campaign_channel_type(data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	values = _normalize(_parse_data(data))
	if not values.get("code") or not values.get("display_name"):
		frappe.throw(_("Code and display name are required."), frappe.ValidationError)
	if not values.get("is_online") and not values.get("is_offline"):
		frappe.throw(_("Select at least one supported mode."), frappe.ValidationError)
	doc = frappe.new_doc("CRM Campaign Channel Type")
	doc.check_permission("create")
	doc.update(values)
	doc.insert()
	return _payload(doc)


@frappe.whitelist(methods=["POST", "PUT"])
def update_campaign_channel_type(name: str, data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	doc = frappe.get_doc("CRM Campaign Channel Type", name)
	doc.check_permission("write")
	values = _normalize(_parse_data(data))
	if "code" in values and values["code"] != doc.code:
		frappe.throw(_("Channel type code is immutable."), frappe.PermissionError)
	values.pop("code", None)
	doc.update(values)
	doc.save()
	return _payload(doc)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_campaign_channel_type(name: str) -> dict[str, str]:
	_require_authentication()
	doc = frappe.get_doc("CRM Campaign Channel Type", name)
	doc.check_permission("delete")
	doc.delete()
	return {"deleted": name}
