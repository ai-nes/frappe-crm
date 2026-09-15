"""Permission-aware CRUD APIs for the Major Group → Major catalog."""

from __future__ import annotations

import re
from typing import Any

import frappe
from frappe import _

from crm.api._pagination import paged_list, parse_pagination

MAJOR_GROUP = "CRM Major Group"
MAJOR = "CRM Major"
STALE_MESSAGE = "Major catalog item changed; reload before retrying."
CONFIGURATION_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,49}$")
MAJOR_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_]{1,49}$")

MAJOR_GROUP_FIELDS = frozenset(
	{
		"code",
		"display_name",
		"name",
		"description",
		"enabled",
		"sort_order",
		"sortOrder",
	}
)
MAJOR_FIELDS = frozenset(
	{
		"major_name",
		"name",
		"major_code",
		"code",
		"degree_name",
		"degreeName",
		"major_group",
		"majorGroup",
		"is_active",
		"isActive",
	}
)


def _require_authentication() -> None:
	user = getattr(getattr(frappe, "session", None), "user", None)
	if not user or user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.AuthenticationError)


def _parse_object(data: dict[str, Any] | str | None, label: str) -> dict[str, Any]:
	if isinstance(data, str):
		try:
			data = frappe.parse_json(data)
		except (TypeError, ValueError):
			data = None
	if not isinstance(data, dict):
		frappe.throw(_("{0} must be an object.").format(label), frappe.ValidationError)
	return data


def _text(value: Any, *, optional: bool = False) -> str | None:
	if value is None:
		return None if optional else ""
	value = str(value).strip()
	return value or (None if optional else "")


def _boolean(value: Any, fieldname: str) -> int:
	if isinstance(value, bool):
		return int(value)
	if isinstance(value, int) and value in (0, 1):
		return value
	value = str(value or "").strip().casefold()
	if value in {"1", "true", "yes", "on"}:
		return 1
	if value in {"0", "false", "no", "off"}:
		return 0
	frappe.throw(_("{0} must be a boolean.").format(fieldname), frappe.ValidationError)


def _non_negative_int(value: Any, fieldname: str) -> int:
	if isinstance(value, bool):
		frappe.throw(_("{0} must be a non-negative integer.").format(fieldname), frappe.ValidationError)
	if isinstance(value, int):
		parsed = value
	elif isinstance(value, float) and value.is_integer():
		parsed = int(value)
	elif isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
		parsed = int(value.strip())
	else:
		frappe.throw(_("{0} must be a non-negative integer.").format(fieldname), frappe.ValidationError)
	if parsed < 0:
		frappe.throw(_("{0} must be a non-negative integer.").format(fieldname), frappe.ValidationError)
	return parsed


def _unknown_fields(data: dict[str, Any], allowed: frozenset[str], label: str) -> None:
	unknown = set(data) - allowed
	if unknown:
		frappe.throw(
			_("Unsupported {0} fields: {1}.").format(label, ", ".join(sorted(unknown))),
			frappe.ValidationError,
		)


def _code(value: Any, label: str) -> str:
	code = (_text(value) or "").upper()
	if not CONFIGURATION_CODE_PATTERN.fullmatch(code):
		frappe.throw(
			_("{0} code must use 2-50 uppercase letters, digits and underscores.").format(label),
			frappe.ValidationError,
		)
	return code


def _major_code(value: Any) -> str:
	code = (_text(value) or "").upper()
	if not MAJOR_CODE_PATTERN.fullmatch(code):
		frappe.throw(
			_("Major code must use 2-50 uppercase letters, digits and underscores."),
			frappe.ValidationError,
		)
	return code


def _normalize_major_group_data(data: dict[str, Any]) -> dict[str, Any]:
	_unknown_fields(data, MAJOR_GROUP_FIELDS, "major group")
	values: dict[str, Any] = {}
	if "code" in data:
		values["code"] = _code(data["code"], "Major Group")
	display_name = data.get("display_name") if "display_name" in data else data.get("name")
	if "display_name" in data or "name" in data:
		values["display_name"] = _text(display_name)
	if "description" in data:
		values["description"] = _text(data["description"], optional=True)
	if "enabled" in data:
		values["enabled"] = _boolean(data["enabled"], "enabled")
	sort_order = "sort_order" if "sort_order" in data else "sortOrder"
	if sort_order in data:
		values["sort_order"] = _non_negative_int(data[sort_order], "sort_order")
	return values


def _normalize_major_data(data: dict[str, Any]) -> dict[str, Any]:
	_unknown_fields(data, MAJOR_FIELDS, "major")
	values: dict[str, Any] = {}
	major_name = data.get("major_name") if "major_name" in data else data.get("name")
	if "major_name" in data or "name" in data:
		values["major_name"] = _text(major_name)
	major_code = data.get("major_code") if "major_code" in data else data.get("code")
	if "major_code" in data or "code" in data:
		values["major_code"] = (
			None if major_code is None or not str(major_code).strip() else _major_code(major_code)
		)
	degree_name = data.get("degree_name") if "degree_name" in data else data.get("degreeName")
	if "degree_name" in data or "degreeName" in data:
		values["degree_name"] = _text(degree_name, optional=True)
	major_group = data.get("major_group") if "major_group" in data else data.get("majorGroup")
	if "major_group" in data or "majorGroup" in data:
		values["major_group"] = _text(major_group, optional=True)
	is_active = "is_active" if "is_active" in data else "isActive"
	if is_active in data:
		values["is_active"] = _boolean(data[is_active], "is_active")
	return values


def _set_values(doc: Any, values: dict[str, Any]) -> None:
	for fieldname, value in values.items():
		doc.set(fieldname, value)


def _value(doc: Any, fieldname: str, default: Any = None) -> Any:
	getter = getattr(doc, "get", None)
	if callable(getter):
		return getter(fieldname, default)
	return getattr(doc, fieldname, default)


def _modified(doc: Any) -> str | None:
	value = _value(doc, "modified")
	return str(value) if value else None


def _assert_expected_modified(doc: Any, expected_modified: str | None) -> None:
	if expected_modified and _modified(doc) != str(expected_modified):
		frappe.throw(_(STALE_MESSAGE), frappe.ValidationError)


def _document_name(name: Any) -> str:
	value = _text(name)
	if not value:
		frappe.throw(_("Document name is required."), frappe.ValidationError)
	return value


def _load_for_update(doctype: str, name: str, expected_modified: str | None) -> Any:
	doc = frappe.get_doc(doctype, _document_name(name))
	doc.check_permission("write")
	_assert_expected_modified(doc, expected_modified)
	return doc


def _group_payload(doc: Any) -> dict[str, Any]:
	return {
		"id": _value(doc, "name"),
		"code": _value(doc, "code"),
		"name": _value(doc, "display_name"),
		"description": _value(doc, "description"),
		"enabled": bool(_value(doc, "enabled")),
		"sortOrder": int(_value(doc, "sort_order") or 0),
		"modified": _modified(doc),
	}


def _group_name(group: str | None) -> str | None:
	if not group:
		return None
	return frappe.db.get_value(MAJOR_GROUP, group, "display_name") or group


def _major_payload(doc: Any) -> dict[str, Any]:
	group = _value(doc, "major_group")
	return {
		"id": _value(doc, "name"),
		"code": _value(doc, "major_code"),
		"name": _value(doc, "major_name") or _value(doc, "name"),
		"degreeName": _value(doc, "degree_name"),
		"majorGroup": group,
		"majorGroupName": _group_name(group),
		"isActive": bool(_value(doc, "is_active")),
		"modified": _modified(doc),
	}


def _assert_group_exists(group: str | None, *, require_enabled: bool = False) -> None:
	if not group:
		frappe.throw(_("Major Group is required for a new Major."), frappe.ValidationError)
	filters: dict[str, Any] = {"name": group}
	if require_enabled:
		filters["enabled"] = 1
	if not frappe.db.exists(MAJOR_GROUP, filters):
		frappe.throw(
			_("Major Group {0} does not exist or is disabled.").format(group), frappe.ValidationError
		)


def _new_document(doctype: str, values: dict[str, Any], *, label: str, unique_field: str) -> Any:
	doc = frappe.new_doc(doctype)
	doc.check_permission("create")
	unique_value = values.get(unique_field)
	if unique_value and frappe.db.exists(doctype, {unique_field: unique_value}):
		frappe.throw(_("{0} {1} already exists.").format(label, unique_value), frappe.DuplicateEntryError)
	_set_values(doc, values)
	doc.insert()
	return doc


def _delete(doctype: str, name: str, expected_modified: str | None) -> dict[str, Any]:
	doc = frappe.get_doc(doctype, _document_name(name))
	doc.check_permission("delete")
	_assert_expected_modified(doc, expected_modified)
	if doctype == MAJOR_GROUP and frappe.db.exists(MAJOR, {"major_group": _value(doc, "name")}):
		frappe.throw(
			_(
				"Cannot delete Major Group {0}: it is referenced by one or more Majors. Disable it instead."
			).format(_value(doc, "display_name") or _value(doc, "name")),
			frappe.ValidationError,
		)
	doc.delete()
	return {"deleted": _value(doc, "name")}


@frappe.whitelist()
def list_major_groups(
	search: str | None = None,
	include_disabled: bool = True,
	enabled: bool | str | None = None,
	start: int | str | None = None,
	page_length: int | str | None = None,
) -> dict[str, Any]:
	"""List Major Groups with optional search, status and pagination filters."""
	include_disabled = bool(_boolean(include_disabled, "include_disabled"))
	is_paginated = start not in (None, "") or page_length not in (None, "")
	if is_paginated:
		start, page_length = parse_pagination(start, page_length)
	filters: dict[str, Any] = {} if include_disabled else {"enabled": 1}
	if enabled not in (None, ""):
		filters["enabled"] = _boolean(enabled, "enabled")
	search_value = _text(search, optional=True) or ""
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [[fieldname, "like", like] for fieldname in ("name", "code", "display_name")]
	fields = ["name", "code", "display_name", "description", "enabled", "sort_order", "modified"]
	if is_paginated:
		result = paged_list(
			MAJOR_GROUP,
			fields,
			filters=filters,
			or_filters=or_filters,
			start=start,
			page_length=page_length,
			order_by="sort_order asc, display_name asc, name asc",
		)
		rows = result.pop("rows")
		return {"groups": [_group_payload(row) for row in rows], **result}
	rows = frappe.get_list(
		MAJOR_GROUP,
		filters=filters,
		or_filters=or_filters,
		fields=fields,
		order_by="sort_order asc, display_name asc, name asc",
		limit_page_length=0,
	)
	return {"groups": [_group_payload(row) for row in rows]}


@frappe.whitelist()
def list_majors(
	search: str | None = None,
	group: str | None = None,
	include_inactive: bool = True,
	is_active: bool | str | None = None,
	start: int | str | None = None,
	page_length: int | str | None = None,
) -> dict[str, Any]:
	"""List child Majors with optional parent, search, status and pagination filters."""
	include_inactive = bool(_boolean(include_inactive, "include_inactive"))
	is_paginated = start not in (None, "") or page_length not in (None, "")
	if is_paginated:
		start, page_length = parse_pagination(start, page_length)
	filters: dict[str, Any] = {} if include_inactive else {"is_active": 1}
	group_value = _text(group, optional=True)
	if group_value:
		filters["major_group"] = group_value
	if is_active not in (None, ""):
		filters["is_active"] = _boolean(is_active, "is_active")
	search_value = _text(search, optional=True) or ""
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [
			[fieldname, "like", like] for fieldname in ("name", "major_name", "major_code", "degree_name")
		]
	fields = [
		"name",
		"major_name",
		"major_code",
		"degree_name",
		"major_group",
		"is_active",
		"modified",
	]
	if is_paginated:
		result = paged_list(
			MAJOR,
			fields,
			filters=filters,
			or_filters=or_filters,
			start=start,
			page_length=page_length,
			order_by="major_name asc, name asc",
		)
		rows = result.pop("rows")
		return {"majors": [_major_payload(row) for row in rows], **result}
	rows = frappe.get_list(
		MAJOR,
		filters=filters,
		or_filters=or_filters,
		fields=fields,
		order_by="major_name asc, name asc",
		limit_page_length=0,
	)
	return {"majors": [_major_payload(row) for row in rows]}


@frappe.whitelist(methods=["POST"])
def create_major_group(data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	values = _normalize_major_group_data(_parse_object(data, _("Major Group")))
	if not values.get("code"):
		frappe.throw(_("Major Group code is required."), frappe.ValidationError)
	if not values.get("display_name"):
		frappe.throw(_("Major Group name is required."), frappe.ValidationError)
	doc = _new_document(MAJOR_GROUP, values, label="Major Group", unique_field="code")
	return _group_payload(doc)


@frappe.whitelist(methods=["POST", "PUT"])
def update_major_group(
	name: str, data: dict[str, Any] | str, expected_modified: str | None = None
) -> dict[str, Any]:
	_require_authentication()
	doc = _load_for_update(MAJOR_GROUP, name, expected_modified)
	values = _normalize_major_group_data(_parse_object(data, _("Major Group")))
	if "code" in values:
		if values["code"] != _value(doc, "code"):
			frappe.throw(_("Major Group code is immutable."), frappe.PermissionError)
		values.pop("code")
	_set_values(doc, values)
	doc.save()
	return _group_payload(doc)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_major_group(name: str, expected_modified: str | None = None) -> dict[str, Any]:
	_require_authentication()
	return _delete(MAJOR_GROUP, name, expected_modified)


@frappe.whitelist(methods=["POST"])
def create_major(data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	values = _normalize_major_data(_parse_object(data, _("Major")))
	if not values.get("major_name"):
		frappe.throw(_("Major name is required."), frappe.ValidationError)
	_assert_group_exists(values.get("major_group"), require_enabled=True)
	doc = _new_document(MAJOR, values, label="Major", unique_field="major_name")
	return _major_payload(doc)


@frappe.whitelist(methods=["POST", "PUT"])
def update_major(
	name: str, data: dict[str, Any] | str, expected_modified: str | None = None
) -> dict[str, Any]:
	_require_authentication()
	doc = _load_for_update(MAJOR, name, expected_modified)
	values = _normalize_major_data(_parse_object(data, _("Major")))
	if "major_name" in values:
		if values["major_name"] != _value(doc, "major_name"):
			frappe.throw(
				_("Major name is immutable because it is the record identifier."), frappe.PermissionError
			)
		values.pop("major_name")
	if "major_code" in values:
		if values["major_code"] != _value(doc, "major_code"):
			frappe.throw(_("Major code is immutable."), frappe.PermissionError)
		values.pop("major_code")
	if values.get("major_group"):
		_assert_group_exists(values["major_group"])
	_set_values(doc, values)
	doc.save()
	return _major_payload(doc)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_major(name: str, expected_modified: str | None = None) -> dict[str, Any]:
	_require_authentication()
	return _delete(MAJOR, name, expected_modified)
