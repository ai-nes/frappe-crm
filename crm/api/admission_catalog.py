"""CRUD APIs for admission document types and admission methods."""

from __future__ import annotations

import re
from typing import Any

import frappe
from frappe import _

DOCUMENT_TYPE = "CRM Document Type"
ADMISSION_METHOD = "CRM Admission Method"
STALE_MESSAGE = "Admission catalog item changed; reload before retrying."
CONFIGURATION_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,49}$")

DOCUMENT_TYPE_FIELDS = frozenset(
	{
		"code",
		"label",
		"name",
		"category",
		"description",
		"conditional_key",
		"conditionalKey",
		"status",
		"is_active",
		"isActive",
	}
)
ADMISSION_METHOD_FIELDS = frozenset(
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

DOCUMENT_TYPE_REFERENCES = (
	("CRM Student Document", "document_type"),
	("CRM Profile Template Document Type", "document_type"),
)
ADMISSION_METHOD_REFERENCES = (
	("CRM Admission Offering", "admission_method"),
	("CRM Admission Application", "admission_method"),
	("CRM Admission Profile Template", "admission_method"),
	("CRM Student", "admission_method"),
	("CRM Lead", "admission_method"),
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


def _normalize_document_type_data(data: dict[str, Any]) -> dict[str, Any]:
	_unknown_fields(data, DOCUMENT_TYPE_FIELDS, "document type")
	values: dict[str, Any] = {}
	if "code" in data:
		values["code"] = (_text(data["code"]) or "").upper()
		if not CONFIGURATION_CODE_PATTERN.fullmatch(values["code"]):
			frappe.throw(
				_("Document Type code must use 2-50 uppercase letters, digits and underscores."),
				frappe.ValidationError,
			)
	label = data.get("label") if "label" in data else data.get("name")
	if "label" in data or "name" in data:
		values["label"] = _text(label)
	if "category" in data:
		values["category"] = (_text(data["category"]) or "").lower()
	if "description" in data:
		values["description"] = _text(data["description"], optional=True)
	conditional_key = "conditional_key" if "conditional_key" in data else "conditionalKey"
	if conditional_key in data:
		values["conditional_key"] = _text(data[conditional_key], optional=True)
	if "status" in data:
		values["status"] = (_text(data["status"]) or "").title()
	is_active = "is_active" if "is_active" in data else "isActive"
	if is_active in data:
		values["is_active"] = _boolean(data[is_active], "is_active")
	return values


def _normalize_admission_method_data(data: dict[str, Any]) -> dict[str, Any]:
	_unknown_fields(data, ADMISSION_METHOD_FIELDS, "admission method")
	values: dict[str, Any] = {}
	if "code" in data:
		values["code"] = (_text(data["code"]) or "").upper()
		if not CONFIGURATION_CODE_PATTERN.fullmatch(values["code"]):
			frappe.throw(
				_("Admission Method code must use 2-50 uppercase letters, digits and underscores."),
				frappe.ValidationError,
			)
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


def _payload(doc: Any, *, document_type: bool) -> dict[str, Any]:
	if document_type:
		return {
			"id": _value(doc, "name"),
			"code": _value(doc, "code"),
			"name": _value(doc, "label"),
			"category": _value(doc, "category"),
			"description": _value(doc, "description"),
			"conditionalKey": _value(doc, "conditional_key"),
			"status": _value(doc, "status"),
			"isActive": bool(_value(doc, "is_active")),
			"modified": _modified(doc),
		}
	return {
		"id": _value(doc, "name"),
		"code": _value(doc, "code"),
		"name": _value(doc, "display_name"),
		"description": _value(doc, "description"),
		"enabled": bool(_value(doc, "enabled")),
		"sortOrder": int(_value(doc, "sort_order") or 0),
		"modified": _modified(doc),
	}


def _referencing_fields(name: str, references: tuple[tuple[str, str], ...]) -> list[str]:
	return [
		f"{doctype}.{fieldname}"
		for doctype, fieldname in references
		if frappe.db.exists(doctype, {fieldname: name})
	]


def _assert_not_referenced(doc: Any, *, document_type: bool) -> None:
	references = DOCUMENT_TYPE_REFERENCES if document_type else ADMISSION_METHOD_REFERENCES
	referencing_fields = _referencing_fields(_value(doc, "name"), references)
	if not referencing_fields:
		return
	entity = "Document Type" if document_type else "Admission Method"
	action = "Archive it" if document_type else "Disable it"
	frappe.throw(
		_("Cannot delete {0} {1}: referenced by {2}. {3} instead.").format(
			entity,
			_value(doc, "code") or _value(doc, "name"),
			", ".join(referencing_fields),
			action,
		),
		frappe.ValidationError,
	)


def _assert_method_can_be_disabled(doc: Any, values: dict[str, Any]) -> None:
	if values.get("enabled", _value(doc, "enabled")):
		return
	method = _value(doc, "name")
	if frappe.db.exists("CRM Admission Profile Template", {"admission_method": method, "status": "Active"}):
		frappe.throw(
			_("Cannot disable Admission Method {0}: it is used by an active profile template.").format(
				_value(doc, "code") or method
			),
			frappe.ValidationError,
		)


def _new_document(doctype: str, values: dict[str, Any], code: str, label: str) -> Any:
	if not code:
		frappe.throw(_("{0} code is required.").format(label), frappe.ValidationError)
	doc = frappe.new_doc(doctype)
	doc.check_permission("create")
	if frappe.db.exists(doctype, {"code": code}):
		frappe.throw(_("{0} code {1} already exists.").format(label, code), frappe.DuplicateEntryError)
	_set_values(doc, values)
	doc.insert()
	return doc


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


def _delete(doctype: str, name: str, expected_modified: str | None, *, document_type: bool) -> dict[str, Any]:
	doc = frappe.get_doc(doctype, _document_name(name))
	doc.check_permission("delete")
	_assert_expected_modified(doc, expected_modified)
	_assert_not_referenced(doc, document_type=document_type)
	doc.delete()
	return {"deleted": _value(doc, "name")}


@frappe.whitelist()
def list_admission_document_types(
	search: str | None = None, include_archived: bool = True
) -> dict[str, list[dict[str, Any]]]:
	"""List admission document types, optionally including archived rows."""
	include_archived = bool(_boolean(include_archived, "include_archived"))
	filters = {"status": ["in", ["Active", "Archived"]] if include_archived else "Active"}
	search_value = _text(search, optional=True) or ""
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [[fieldname, "like", like] for fieldname in ("name", "code", "label", "category")]
	rows = frappe.get_list(
		DOCUMENT_TYPE,
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"code",
			"label",
			"category",
			"description",
			"conditional_key",
			"status",
			"is_active",
			"modified",
		],
		order_by="label asc, name asc",
		limit_page_length=0,
	)
	return {"documentTypes": [_payload(row, document_type=True) for row in rows]}


@frappe.whitelist(methods=["POST"])
def create_admission_document_type(data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	values = _normalize_document_type_data(_parse_object(data, _("Document Type")))
	code = values.get("code", "")
	doc = _new_document(DOCUMENT_TYPE, values, code, "Document Type")
	return _payload(doc, document_type=True)


@frappe.whitelist(methods=["POST", "PUT"])
def update_admission_document_type(
	name: str, data: dict[str, Any] | str, expected_modified: str | None = None
) -> dict[str, Any]:
	_require_authentication()
	doc = _load_for_update(DOCUMENT_TYPE, name, expected_modified)
	values = _normalize_document_type_data(_parse_object(data, _("Document Type")))
	if "code" in values:
		if values["code"] != _value(doc, "code"):
			frappe.throw(_("Document Type code is immutable."), frappe.PermissionError)
		values.pop("code")
	_set_values(doc, values)
	doc.save()
	return _payload(doc, document_type=True)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_admission_document_type(name: str, expected_modified: str | None = None) -> dict[str, Any]:
	_require_authentication()
	return _delete(DOCUMENT_TYPE, name, expected_modified, document_type=True)


@frappe.whitelist()
def list_admission_methods(
	search: str | None = None, include_disabled: bool = True
) -> dict[str, list[dict[str, Any]]]:
	"""List admission methods, optionally excluding disabled rows."""
	include_disabled = bool(_boolean(include_disabled, "include_disabled"))
	filters = {} if include_disabled else {"enabled": 1}
	search_value = _text(search, optional=True) or ""
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [[fieldname, "like", like] for fieldname in ("name", "code", "display_name")]
	rows = frappe.get_list(
		ADMISSION_METHOD,
		filters=filters,
		or_filters=or_filters,
		fields=["name", "code", "display_name", "description", "enabled", "sort_order", "modified"],
		order_by="sort_order asc, display_name asc, name asc",
		limit_page_length=0,
	)
	return {"methods": [_payload(row, document_type=False) for row in rows]}


@frappe.whitelist(methods=["POST"])
def create_admission_method(data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	values = _normalize_admission_method_data(_parse_object(data, _("Admission Method")))
	code = values.get("code", "")
	doc = _new_document(ADMISSION_METHOD, values, code, "Admission Method")
	return _payload(doc, document_type=False)


@frappe.whitelist(methods=["POST", "PUT"])
def update_admission_method(
	name: str, data: dict[str, Any] | str, expected_modified: str | None = None
) -> dict[str, Any]:
	_require_authentication()
	doc = _load_for_update(ADMISSION_METHOD, name, expected_modified)
	values = _normalize_admission_method_data(_parse_object(data, _("Admission Method")))
	if "code" in values:
		if values["code"] != _value(doc, "code"):
			frappe.throw(_("Admission Method code is immutable."), frappe.PermissionError)
		values.pop("code")
	_assert_method_can_be_disabled(doc, values)
	_set_values(doc, values)
	doc.save()
	return _payload(doc, document_type=False)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_admission_method(name: str, expected_modified: str | None = None) -> dict[str, Any]:
	_require_authentication()
	return _delete(ADMISSION_METHOD, name, expected_modified, document_type=False)
