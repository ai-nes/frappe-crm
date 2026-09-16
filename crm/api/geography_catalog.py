"""Permission-aware CRUD APIs for admission reference catalogs."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import frappe
from frappe import _

from crm.api._pagination import paged_list, parse_pagination

PROVINCE = "CRM Province"
WARD = "CRM Ward"
HIGH_SCHOOL = "CRM High School"
SCHOOL_AREA = "CRM School Area"
STALE_MESSAGE = "Admission catalog item changed; reload before retrying."
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$")
LOOKUP_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,49}$")
CITY_TYPES = {"Centrally Controlled City", "Province"}
WARD_TYPES = {"Ward", "Commune", "Township"}
SCHOOL_TIERS = {"A", "B", "C", "Unclassified"}
BOARDING_TYPES = {"Day School", "Boarding School", "Mixed", "Unknown"}

PROVINCE_FIELDS = frozenset({"province_code", "province_name", "region", "city_type"})
WARD_FIELDS = frozenset({"ward_code", "ward_name", "ward_type", "province", "zone"})
SCHOOL_FIELDS = frozenset(
	{
		"school_name",
		"school_code",
		"school_type",
		"school_area",
		"school_tier",
		"boarding_type",
		"is_active",
		"province",
		"ward",
		"address",
		"phone",
		"email",
	}
)
SCHOOL_AREA_FIELDS = frozenset(
	{"code", "display_name", "name", "description", "enabled", "sort_order", "sortOrder"}
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


def _identifier(value: Any, label: str) -> str:
	identifier = _text(value) or ""
	if not IDENTIFIER_PATTERN.fullmatch(identifier):
		frappe.throw(
			_("{0} must use up to 50 letters, digits, hyphens or underscores.").format(label),
			frappe.ValidationError,
		)
	return identifier


def _lookup_code(value: Any, label: str) -> str:
	code = (_text(value) or "").upper()
	if not LOOKUP_CODE_PATTERN.fullmatch(code):
		frappe.throw(
			_("{0} code must use 2-50 uppercase letters, digits and underscores.").format(label),
			frappe.ValidationError,
		)
	return code


def _enum(value: Any, values: set[str], fieldname: str, *, optional: bool = False) -> str | None:
	parsed = _text(value, optional=optional)
	if parsed is None and optional:
		return None
	if parsed not in values:
		frappe.throw(
			_("{0} must be one of: {1}.").format(fieldname, ", ".join(sorted(values))),
			frappe.ValidationError,
		)
	return parsed


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


def _assert_exists(doctype: str, name: str | None, label: str) -> None:
	if name and not frappe.db.exists(doctype, name):
		frappe.throw(_("{0} {1} does not exist.").format(label, name), frappe.ValidationError)


def _new_document(
	doctype: str,
	values: dict[str, Any],
	*,
	label: str,
	unique_filters: dict[str, Any] | None = None,
) -> Any:
	doc = frappe.new_doc(doctype)
	doc.check_permission("create")
	if unique_filters and frappe.db.exists(doctype, unique_filters):
		frappe.throw(
			_("{0} already exists.").format(label),
			frappe.DuplicateEntryError,
		)
	_set_values(doc, values)
	doc.insert()
	return doc


def _delete(doctype: str, name: str, expected_modified: str | None) -> dict[str, Any]:
	doc = frappe.get_doc(doctype, _document_name(name))
	doc.check_permission("delete")
	_assert_expected_modified(doc, expected_modified)
	doc.delete()
	return {"deleted": _value(doc, "name")}


def _lookup_label(doctype: str, name: str | None, fieldname: str) -> str | None:
	if not name:
		return None
	return frappe.db.get_value(doctype, name, fieldname) or name


def _province_payload(doc: Any) -> dict[str, Any]:
	region = _value(doc, "region")
	return {
		"id": _value(doc, "name"),
		"code": _value(doc, "province_code"),
		"name": _value(doc, "province_name") or _value(doc, "name"),
		"region": region,
		"regionName": _lookup_label("CRM Region", region, "display_name"),
		"cityType": _value(doc, "city_type"),
		"modified": _modified(doc),
	}


def _ward_payload(doc: Any) -> dict[str, Any]:
	province = _value(doc, "province")
	zone = _value(doc, "zone")
	return {
		"id": _value(doc, "name"),
		"code": _value(doc, "ward_code"),
		"name": _value(doc, "ward_name") or _value(doc, "name"),
		"wardType": _value(doc, "ward_type"),
		"province": province,
		"provinceName": _lookup_label(PROVINCE, province, "province_name"),
		"zone": zone,
		"zoneName": _lookup_label("CRM Zone", zone, "zone_name"),
		"modified": _modified(doc),
	}


def _school_payload(doc: Any) -> dict[str, Any]:
	province = _value(doc, "province")
	ward = _value(doc, "ward")
	school_type = _value(doc, "school_type")
	school_area = _value(doc, "school_area")
	return {
		"id": _value(doc, "name"),
		"code": _value(doc, "school_code"),
		"name": _value(doc, "school_name") or _value(doc, "name"),
		"schoolType": school_type,
		"schoolTypeName": _lookup_label("CRM School Type", school_type, "display_name"),
		"schoolArea": school_area,
		"schoolAreaName": _lookup_label(SCHOOL_AREA, school_area, "display_name"),
		"schoolTier": _value(doc, "school_tier"),
		"boardingType": _value(doc, "boarding_type"),
		"isActive": bool(_value(doc, "is_active")),
		"province": province,
		"provinceName": _lookup_label(PROVINCE, province, "province_name"),
		"ward": ward,
		"wardName": _lookup_label(WARD, ward, "ward_name"),
		"address": _value(doc, "address"),
		"phone": _value(doc, "phone"),
		"email": _value(doc, "email"),
		"modified": _modified(doc),
	}


def _school_area_payload(doc: Any) -> dict[str, Any]:
	return {
		"id": _value(doc, "name"),
		"code": _value(doc, "code"),
		"name": _value(doc, "display_name"),
		"description": _value(doc, "description"),
		"enabled": bool(_value(doc, "enabled")),
		"sortOrder": int(_value(doc, "sort_order") or 0),
		"modified": _modified(doc),
	}


def _list_catalog(
	doctype: str,
	fields: list[str],
	filters: dict[str, Any],
	search: str | None,
	search_fields: tuple[str, ...],
	order_by: str,
	response_key: str,
	mapper: Callable[[Any], dict[str, Any]],
	start: int | str | None,
	page_length: int | str | None,
) -> dict[str, Any]:
	is_paginated = start not in (None, "") or page_length not in (None, "")
	if is_paginated:
		start, page_length = parse_pagination(start, page_length)
	search_value = _text(search, optional=True) or ""
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [[fieldname, "like", like] for fieldname in search_fields]
	if is_paginated:
		result = paged_list(
			doctype,
			fields,
			filters=filters,
			or_filters=or_filters,
			start=start,
			page_length=page_length,
			order_by=order_by,
		)
		rows = result.pop("rows")
		return {response_key: [mapper(row) for row in rows], **result}
	rows = frappe.get_list(
		doctype,
		filters=filters,
		or_filters=or_filters,
		fields=fields,
		order_by=order_by,
		limit_page_length=0,
	)
	return {response_key: [mapper(row) for row in rows]}


def _normalize_province_data(data: dict[str, Any]) -> dict[str, Any]:
	_unknown_fields(data, PROVINCE_FIELDS, "province")
	values: dict[str, Any] = {}
	if "province_code" in data:
		values["province_code"] = _identifier(data["province_code"], "Province code")
	if "province_name" in data:
		values["province_name"] = _text(data["province_name"])
	if "region" in data:
		values["region"] = _text(data["region"], optional=True)
	if "city_type" in data:
		values["city_type"] = _enum(data["city_type"], CITY_TYPES, "city_type")
	return values


def _normalize_ward_data(data: dict[str, Any]) -> dict[str, Any]:
	_unknown_fields(data, WARD_FIELDS, "ward")
	values: dict[str, Any] = {}
	if "ward_code" in data:
		values["ward_code"] = _identifier(data["ward_code"], "Ward code")
	if "ward_name" in data:
		values["ward_name"] = _text(data["ward_name"])
	if "ward_type" in data:
		values["ward_type"] = _enum(data["ward_type"], WARD_TYPES, "ward_type")
	if "province" in data:
		values["province"] = _text(data["province"], optional=True)
	if "zone" in data:
		values["zone"] = _text(data["zone"], optional=True)
	return values


def _validate_ward_geography(values: dict[str, Any]) -> None:
	province = values.get("province")
	_assert_exists(PROVINCE, province, "Province")
	zone = values.get("zone")
	if not zone:
		return
	_assert_exists("CRM Zone", zone, "Zone")
	cluster = frappe.db.get_value("CRM Zone", zone, "cluster")
	zone_province = frappe.db.get_value("CRM Cluster", cluster, "province") if cluster else None
	if zone_province and zone_province != province:
		frappe.throw(
			_("Zone {0} does not belong to Province {1}.").format(zone, province),
			frappe.ValidationError,
		)


def _normalize_school_data(data: dict[str, Any]) -> dict[str, Any]:
	_unknown_fields(data, SCHOOL_FIELDS, "high school")
	values: dict[str, Any] = {}
	for fieldname in ("school_name", "school_code", "province", "ward"):
		if fieldname in data:
			values[fieldname] = _text(data[fieldname], optional=True)
	for fieldname in ("school_type", "school_area", "address", "phone", "email"):
		if fieldname in data:
			values[fieldname] = _text(data[fieldname], optional=True)
	if "school_tier" in data:
		values["school_tier"] = _enum(data["school_tier"], SCHOOL_TIERS, "school_tier", optional=True)
	if "boarding_type" in data:
		values["boarding_type"] = _enum(data["boarding_type"], BOARDING_TYPES, "boarding_type", optional=True)
	if "is_active" in data:
		values["is_active"] = _boolean(data["is_active"], "is_active")
	return values


def _normalize_school_area_data(data: dict[str, Any]) -> dict[str, Any]:
	_unknown_fields(data, SCHOOL_AREA_FIELDS, "school area")
	values: dict[str, Any] = {}
	if "code" in data:
		values["code"] = _lookup_code(data["code"], "School area")
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


@frappe.whitelist()
def list_provinces(
	search: str | None = None,
	region: str | None = None,
	city_type: str | None = None,
	start: int | str | None = None,
	page_length: int | str | None = None,
) -> dict[str, Any]:
	_require_authentication()
	filters: dict[str, Any] = {}
	if region:
		filters["region"] = _text(region)
	if city_type:
		filters["city_type"] = _enum(city_type, CITY_TYPES, "city_type")
	return _list_catalog(
		PROVINCE,
		["name", "province_code", "province_name", "region", "city_type", "modified"],
		filters,
		search,
		("name", "province_code", "province_name"),
		"province_name asc, name asc",
		"provinces",
		_province_payload,
		start,
		page_length,
	)


@frappe.whitelist()
def list_wards(
	search: str | None = None,
	province: str | None = None,
	zone: str | None = None,
	ward_type: str | None = None,
	start: int | str | None = None,
	page_length: int | str | None = None,
) -> dict[str, Any]:
	_require_authentication()
	filters: dict[str, Any] = {}
	if province:
		filters["province"] = _text(province)
	if zone:
		filters["zone"] = _text(zone)
	if ward_type:
		filters["ward_type"] = _enum(ward_type, WARD_TYPES, "ward_type")
	return _list_catalog(
		WARD,
		["name", "ward_code", "ward_name", "ward_type", "province", "zone", "modified"],
		filters,
		search,
		("name", "ward_code", "ward_name"),
		"ward_name asc, name asc",
		"wards",
		_ward_payload,
		start,
		page_length,
	)


@frappe.whitelist()
def list_high_schools(
	search: str | None = None,
	province: str | None = None,
	ward: str | None = None,
	school_area: str | None = None,
	is_active: bool | str | None = None,
	start: int | str | None = None,
	page_length: int | str | None = None,
) -> dict[str, Any]:
	_require_authentication()
	filters: dict[str, Any] = {}
	if province:
		filters["province"] = _text(province)
	if ward:
		filters["ward"] = _text(ward)
	if school_area:
		filters["school_area"] = _text(school_area)
	if is_active not in (None, ""):
		filters["is_active"] = _boolean(is_active, "is_active")
	return _list_catalog(
		HIGH_SCHOOL,
		[
			"name",
			"school_name",
			"school_code",
			"school_type",
			"school_area",
			"school_tier",
			"boarding_type",
			"is_active",
			"province",
			"ward",
			"address",
			"phone",
			"email",
			"modified",
		],
		filters,
		search,
		("name", "school_name", "school_code"),
		"school_name asc, name asc",
		"schools",
		_school_payload,
		start,
		page_length,
	)


@frappe.whitelist()
def list_school_areas(
	search: str | None = None,
	include_disabled: bool = True,
	enabled: bool | str | None = None,
	start: int | str | None = None,
	page_length: int | str | None = None,
) -> dict[str, Any]:
	_require_authentication()
	filters: dict[str, Any] = {}
	if not _boolean(include_disabled, "include_disabled"):
		filters["enabled"] = 1
	if enabled not in (None, ""):
		filters["enabled"] = _boolean(enabled, "enabled")
	return _list_catalog(
		SCHOOL_AREA,
		["name", "code", "display_name", "description", "enabled", "sort_order", "modified"],
		filters,
		search,
		("name", "code", "display_name"),
		"sort_order asc, display_name asc, name asc",
		"schoolAreas",
		_school_area_payload,
		start,
		page_length,
	)


@frappe.whitelist()
def list_geography_options(province: str | None = None) -> dict[str, Any]:
	"""Return linked options needed by the province, ward and school editors."""
	_require_authentication()
	province_value = _text(province, optional=True)
	regions = frappe.get_list(
		"CRM Region",
		filters={"enabled": 1},
		fields=["name", "code", "display_name"],
		order_by="sort_order asc, display_name asc, name asc",
		limit_page_length=0,
	)
	provinces = frappe.get_list(
		PROVINCE,
		fields=["name", "province_code", "province_name"],
		order_by="province_name asc, name asc",
		limit_page_length=0,
	)
	ward_filters = {"province": province_value} if province_value else {}
	wards = frappe.get_list(
		WARD,
		filters=ward_filters,
		fields=["name", "ward_code", "ward_name", "province", "zone"],
		order_by="ward_name asc, name asc",
		limit_page_length=0,
	)
	zones = frappe.get_list(
		"CRM Zone",
		fields=["name", "zone_name", "zone_code", "cluster"],
		order_by="zone_name asc, name asc",
		limit_page_length=0,
	)
	zone_options = []
	for zone in zones:
		cluster = zone.get("cluster")
		zone_province = frappe.db.get_value("CRM Cluster", cluster, "province") if cluster else None
		if province_value and zone_province != province_value:
			continue
		zone_options.append(
			{
				"id": zone.get("name"),
				"code": zone.get("zone_code"),
				"name": zone.get("zone_name") or zone.get("name"),
				"province": zone_province,
			}
		)
	school_areas = frappe.get_list(
		SCHOOL_AREA,
		filters={"enabled": 1},
		fields=["name", "code", "display_name"],
		order_by="sort_order asc, display_name asc, name asc",
		limit_page_length=0,
	)
	school_types = frappe.get_list(
		"CRM School Type",
		filters={"enabled": 1},
		fields=["name", "code", "display_name"],
		order_by="sort_order asc, display_name asc, name asc",
		limit_page_length=0,
	)
	return {
		"regions": [
			{"id": row.get("name"), "code": row.get("code"), "name": row.get("display_name")}
			for row in regions
		],
		"provinces": [
			{"id": row.get("name"), "code": row.get("province_code"), "name": row.get("province_name")}
			for row in provinces
		],
		"wards": [
			{
				"id": row.get("name"),
				"code": row.get("ward_code"),
				"name": row.get("ward_name"),
				"province": row.get("province"),
				"zone": row.get("zone"),
			}
			for row in wards
		],
		"zones": zone_options,
		"schoolAreas": [
			{"id": row.get("name"), "code": row.get("code"), "name": row.get("display_name")}
			for row in school_areas
		],
		"schoolTypes": [
			{"id": row.get("name"), "code": row.get("code"), "name": row.get("display_name")}
			for row in school_types
		],
	}


@frappe.whitelist(methods=["POST"])
def create_province(data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	values = _normalize_province_data(_parse_object(data, _("Province")))
	if not values.get("province_code") or not values.get("province_name"):
		frappe.throw(_("Province code and name are required."), frappe.ValidationError)
	_assert_exists("CRM Region", values.get("region"), "Region")
	values.setdefault("city_type", "Province")
	doc = _new_document(
		PROVINCE,
		values,
		label=f"Province {values['province_code']}",
		unique_filters={"province_code": values["province_code"]},
	)
	return _province_payload(doc)


@frappe.whitelist(methods=["POST", "PUT"])
def update_province(
	name: str, data: dict[str, Any] | str, expected_modified: str | None = None
) -> dict[str, Any]:
	_require_authentication()
	doc = _load_for_update(PROVINCE, name, expected_modified)
	values = _normalize_province_data(_parse_object(data, _("Province")))
	for fieldname in ("province_code", "province_name"):
		if fieldname in values and values[fieldname] != _value(doc, fieldname):
			frappe.throw(_("Province code and name are immutable."), frappe.PermissionError)
		values.pop(fieldname, None)
	_assert_exists("CRM Region", values.get("region"), "Region")
	_set_values(doc, values)
	doc.save()
	return _province_payload(doc)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_province(name: str, expected_modified: str | None = None) -> dict[str, Any]:
	_require_authentication()
	return _delete(PROVINCE, name, expected_modified)


@frappe.whitelist(methods=["POST"])
def create_ward(data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	values = _normalize_ward_data(_parse_object(data, _("Ward")))
	if not values.get("ward_code") or not values.get("ward_name") or not values.get("province"):
		frappe.throw(_("Ward code, name and province are required."), frappe.ValidationError)
	_validate_ward_geography(values)
	values.setdefault("ward_type", "Ward")
	doc = _new_document(
		WARD,
		values,
		label=f"Ward {values['ward_code']}",
		unique_filters={"ward_code": values["ward_code"], "province": values["province"]},
	)
	return _ward_payload(doc)


@frappe.whitelist(methods=["POST", "PUT"])
def update_ward(
	name: str, data: dict[str, Any] | str, expected_modified: str | None = None
) -> dict[str, Any]:
	_require_authentication()
	doc = _load_for_update(WARD, name, expected_modified)
	values = _normalize_ward_data(_parse_object(data, _("Ward")))
	for fieldname in ("ward_code", "ward_name"):
		if fieldname in values and values[fieldname] != _value(doc, fieldname):
			frappe.throw(_("Ward code and name are immutable."), frappe.PermissionError)
		values.pop(fieldname, None)
	if "province" in values and values["province"] != _value(doc, "province") and "zone" not in values:
		values["zone"] = None
	if "province" in values or "zone" in values:
		geography = {
			"province": values.get("province", _value(doc, "province")),
			"zone": values.get("zone", _value(doc, "zone")),
		}
		_validate_ward_geography(geography)
	_set_values(doc, values)
	doc.save()
	return _ward_payload(doc)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_ward(name: str, expected_modified: str | None = None) -> dict[str, Any]:
	_require_authentication()
	return _delete(WARD, name, expected_modified)


def _validate_school_links(values: dict[str, Any]) -> None:
	_assert_exists(PROVINCE, values.get("province"), "Province")
	_assert_exists(WARD, values.get("ward"), "Ward")
	_assert_exists("CRM School Type", values.get("school_type"), "School type")
	_assert_exists(SCHOOL_AREA, values.get("school_area"), "School area")


@frappe.whitelist(methods=["POST"])
def create_high_school(data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	values = _normalize_school_data(_parse_object(data, _("High School")))
	if not values.get("school_name") or not values.get("school_code"):
		frappe.throw(_("School name and code are required."), frappe.ValidationError)
	if not values.get("province") or not values.get("ward"):
		frappe.throw(_("Province and ward are required."), frappe.ValidationError)
	_validate_school_links(values)
	values.setdefault("is_active", 1)
	doc = _new_document(HIGH_SCHOOL, values, label=f"High School {values['school_code']}")
	return _school_payload(doc)


@frappe.whitelist(methods=["POST", "PUT"])
def update_high_school(
	name: str, data: dict[str, Any] | str, expected_modified: str | None = None
) -> dict[str, Any]:
	_require_authentication()
	doc = _load_for_update(HIGH_SCHOOL, name, expected_modified)
	values = _normalize_school_data(_parse_object(data, _("High School")))
	merged = {fieldname: _value(doc, fieldname) for fieldname in SCHOOL_FIELDS}
	merged.update(values)
	if not merged.get("school_name") or not merged.get("school_code"):
		frappe.throw(_("School name and code are required."), frappe.ValidationError)
	if not merged.get("province") or not merged.get("ward"):
		frappe.throw(_("Province and ward are required."), frappe.ValidationError)
	_validate_school_links(merged)
	_set_values(doc, values)
	doc.save()
	return _school_payload(doc)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_high_school(name: str, expected_modified: str | None = None) -> dict[str, Any]:
	_require_authentication()
	return _delete(HIGH_SCHOOL, name, expected_modified)


@frappe.whitelist(methods=["POST"])
def create_school_area(data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	values = _normalize_school_area_data(_parse_object(data, _("School area")))
	if not values.get("code") or not values.get("display_name"):
		frappe.throw(_("School area code and name are required."), frappe.ValidationError)
	values.setdefault("enabled", 1)
	doc = _new_document(
		SCHOOL_AREA,
		values,
		label=f"School area {values['code']}",
		unique_filters={"code": values["code"]},
	)
	return _school_area_payload(doc)


@frappe.whitelist(methods=["POST", "PUT"])
def update_school_area(
	name: str, data: dict[str, Any] | str, expected_modified: str | None = None
) -> dict[str, Any]:
	_require_authentication()
	doc = _load_for_update(SCHOOL_AREA, name, expected_modified)
	values = _normalize_school_area_data(_parse_object(data, _("School area")))
	if "code" in values:
		if values["code"] != _value(doc, "code"):
			frappe.throw(_("School area code is immutable."), frappe.PermissionError)
		values.pop("code")
	_set_values(doc, values)
	doc.save()
	return _school_area_payload(doc)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_school_area(name: str, expected_modified: str | None = None) -> dict[str, Any]:
	_require_authentication()
	return _delete(SCHOOL_AREA, name, expected_modified)
