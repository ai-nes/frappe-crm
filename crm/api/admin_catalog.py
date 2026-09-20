"""Admin command boundaries for admission, policy and campaign catalogs."""

from __future__ import annotations

import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import getdate

from crm.api._pagination import paged_list, parse_pagination
from crm.fcrm.admission_offering import approve_offering
from crm.fcrm.governed_reference_registry import GOVERNED_REFERENCE_REGISTRY
from crm.fcrm.master_data_governance import (
	approve_change,
	create_additive_value,
	list_pending_changes,
	propose_change,
)

ADMISSION_YEAR = "CRM Admission Year"
ACADEMIC_YEAR_CONFIG = "CRM Academic Year Config"
ADMISSION_OFFERING = "CRM Admission Offering"
SCORE_TEMPLATE = "CRM Score Template"
SCORE_SIGNAL = "CRM Score Signal"

GOVERNED_FIELDS = {
	"CRM Campus": [
		"name",
		"campus_name",
		"campus_code",
		"is_default",
		"province",
		"city",
		"latitude",
		"longitude",
		"address",
		"phone",
		"owner_role",
		"approval_state",
		"version",
		"effective_date",
	],
	"CRM Lead Source": [
		"name",
		"source_name",
		"is_digital",
		"channel_family",
		"details",
		"owner_role",
		"approval_state",
		"version",
		"effective_date",
	],
	"CRM Platform": [
		"name",
		"platform_name",
		"lead_source",
		"sub_channel",
		"channel_url",
		"owner_role",
		"approval_state",
		"version",
		"effective_date",
	],
}
GOVERNED_VALUE_FIELDS = {
	"CRM Campus": "campus_name",
	"CRM Lead Source": "source_name",
	"CRM Platform": "platform_name",
}

OFFERING_FIELDS = [
	"name",
	"offering_key",
	"admission_year",
	"campus",
	"major",
	"admission_method",
	"quota",
	"effective_from",
	"effective_until",
	"status",
	"policy_version",
	"approved_by",
	"approved_at",
	"modified",
]
SCORE_TEMPLATE_FIELDS = [
	"name",
	"template_name",
	"status",
	"start_time",
	"end_time",
	"policy_revision",
	"policy_hash",
	"fit_weight",
	"engagement_weight",
	"intent_weight",
	"modified",
]
SCORE_SIGNAL_FIELDS = [
	"name",
	"signal_key",
	"label",
	"category",
	"signal_type",
	"is_active",
	"description",
]
YEAR_FIELDS = ["name", "year_name", "start_date", "end_date", "is_active", "modified"]
CONFIG_FIELDS = ["name", "admission_year", "config_name", "notes", "modified"]
CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,49}$")


def _require_authentication() -> None:
	if getattr(getattr(frappe, "session", None), "user", "Guest") == "Guest":
		frappe.throw(_("Authentication is required."), frappe.AuthenticationError)


def _parse_data(data: dict[str, Any] | str | None, label: str) -> dict[str, Any]:
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


def _modified(doc: Any) -> str | None:
	value = doc.get("modified")
	return str(value) if value else None


def _assert_expected_modified(doc: Any, expected_modified: str | None) -> None:
	if expected_modified and _modified(doc) != str(expected_modified):
		frappe.throw(_("The record changed; reload before retrying."), frappe.ValidationError)


def _paginate(
	doctype: str, fields: list[str], search: str | None, start: Any, page_length: Any, *, order_by: str
) -> dict[str, Any]:
	start, page_length = parse_pagination(start, page_length)
	search_value = _text(search, optional=True)
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [
			[field, "like", like]
			for field in ("name", "year_name", "config_name", "template_name")
			if field in fields
		]
	result = paged_list(
		doctype,
		fields,
		or_filters=or_filters,
		start=start,
		page_length=page_length,
		order_by=order_by,
	)
	rows = result.pop("rows")
	return {"rows": [dict(row) for row in rows], **result}


@frappe.whitelist()
def list_admission_years(
	search: str | None = None, start: int | str = 0, page_length: int | str = 50
) -> dict[str, Any]:
	_require_authentication()
	result = _paginate(
		ADMISSION_YEAR, YEAR_FIELDS, search, start, page_length, order_by="year_name desc, name desc"
	)
	return {"years": result.pop("rows"), **result}


@frappe.whitelist(methods=["POST"])
def create_admission_year(data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	values = _parse_data(data, _("Admission Year"))
	allowed = {"year_name", "start_date", "end_date", "is_active"}
	doc = frappe.new_doc(ADMISSION_YEAR)
	doc.check_permission("create")
	doc.update({key: values[key] for key in allowed if key in values})
	doc.insert()
	return doc.as_dict()


@frappe.whitelist(methods=["POST", "PUT"])
def update_admission_year(
	name: str, data: dict[str, Any] | str, expected_modified: str | None = None
) -> dict[str, Any]:
	_require_authentication()
	doc = frappe.get_doc(ADMISSION_YEAR, name)
	doc.check_permission("write")
	_assert_expected_modified(doc, expected_modified)
	allowed = {"year_name", "start_date", "end_date", "is_active"}
	values = _parse_data(data, _("Admission Year"))
	doc.update({key: values[key] for key in allowed if key in values})
	doc.save()
	return doc.as_dict()


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_admission_year(name: str, expected_modified: str | None = None) -> dict[str, str]:
	_require_authentication()
	doc = frappe.get_doc(ADMISSION_YEAR, name)
	doc.check_permission("delete")
	_assert_expected_modified(doc, expected_modified)
	if frappe.db.exists(ACADEMIC_YEAR_CONFIG, {"admission_year": name}) or frappe.db.exists(
		ADMISSION_OFFERING, {"admission_year": name}
	):
		frappe.throw(
			_("Admission Year is referenced by another catalog; deactivate it instead."),
			frappe.ValidationError,
		)
	doc.delete()
	return {"deleted": name}


def _config_payload(doc: Any) -> dict[str, Any]:
	result = doc.as_dict()
	result["lines"] = [dict(line) for line in (doc.lines or [])]
	return result


@frappe.whitelist()
def list_academic_year_configs(
	search: str | None = None, start: int | str = 0, page_length: int | str = 50
) -> dict[str, Any]:
	_require_authentication()
	result = _paginate(
		ACADEMIC_YEAR_CONFIG, CONFIG_FIELDS, search, start, page_length, order_by="modified desc, name desc"
	)
	configs = [
		_config_payload(frappe.get_doc(ACADEMIC_YEAR_CONFIG, row["name"])) for row in result.pop("rows")
	]
	return {"configs": configs, **result}


def _save_config(values: dict[str, Any], doc: Any | None = None) -> dict[str, Any]:
	allowed = {"admission_year", "config_name", "notes", "lines"}
	if doc is None:
		doc = frappe.new_doc(ACADEMIC_YEAR_CONFIG)
		doc.check_permission("create")
	else:
		doc.check_permission("write")
	doc.update({key: values[key] for key in allowed if key in values})
	doc.save() if not doc.is_new() else doc.insert()
	return _config_payload(doc)


@frappe.whitelist(methods=["POST"])
def create_academic_year_config(data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	return _save_config(_parse_data(data, _("Academic Year Config")))


@frappe.whitelist(methods=["POST", "PUT"])
def update_academic_year_config(
	name: str, data: dict[str, Any] | str, expected_modified: str | None = None
) -> dict[str, Any]:
	_require_authentication()
	doc = frappe.get_doc(ACADEMIC_YEAR_CONFIG, name)
	_assert_expected_modified(doc, expected_modified)
	return _save_config(_parse_data(data, _("Academic Year Config")), doc)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_academic_year_config(name: str, expected_modified: str | None = None) -> dict[str, str]:
	_require_authentication()
	doc = frappe.get_doc(ACADEMIC_YEAR_CONFIG, name)
	doc.check_permission("delete")
	_assert_expected_modified(doc, expected_modified)
	doc.delete()
	return {"deleted": name}


@frappe.whitelist()
def list_admission_offerings(
	search: str | None = None, status: str | None = None, start: int | str = 0, page_length: int | str = 50
) -> dict[str, Any]:
	_require_authentication()
	start, page_length = parse_pagination(start, page_length)
	filters = {"status": _text(status)} if _text(status, optional=True) else {}
	search_value = _text(search, optional=True)
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [
			[field, "like", like] for field in ("name", "offering_key", "campus", "major", "admission_year")
		]
	result = paged_list(
		ADMISSION_OFFERING,
		OFFERING_FIELDS,
		filters=filters,
		or_filters=or_filters,
		start=start,
		page_length=page_length,
		order_by="effective_from desc, name desc",
	)
	rows = result.pop("rows")
	return {"offerings": [dict(row) for row in rows], **result}


def _offering_values(values: dict[str, Any]) -> dict[str, Any]:
	allowed = {
		"admission_year",
		"campus",
		"major",
		"admission_method",
		"quota",
		"effective_from",
		"effective_until",
		"status",
	}
	result = {key: values[key] for key in allowed if key in values}
	if result.get("status") == "Active":
		frappe.throw(_("Active offerings must be activated through approval."), frappe.PermissionError)
	return result


@frappe.whitelist(methods=["POST"])
def create_admission_offering(data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	doc = frappe.new_doc(ADMISSION_OFFERING)
	doc.check_permission("create")
	doc.update(_offering_values(_parse_data(data, _("Admission Offering"))))
	doc.insert()
	return doc.as_dict()


@frappe.whitelist(methods=["POST", "PUT"])
def update_admission_offering(
	name: str, data: dict[str, Any] | str, expected_modified: str | None = None
) -> dict[str, Any]:
	_require_authentication()
	doc = frappe.get_doc(ADMISSION_OFFERING, name)
	doc.check_permission("write")
	_assert_expected_modified(doc, expected_modified)
	doc.update(_offering_values(_parse_data(data, _("Admission Offering"))))
	doc.save()
	return doc.as_dict()


@frappe.whitelist(methods=["POST"])
def transition_admission_offering(
	name: str, status: str, expected_modified: str | None = None, idempotency_key: str | None = None
) -> dict[str, Any]:
	_require_authentication()
	status = _text(status) or ""
	doc = frappe.get_doc(ADMISSION_OFFERING, name)
	_assert_expected_modified(doc, expected_modified)
	if status == "Active":
		approve_offering(offering=name, idempotency_key=idempotency_key or frappe.generate_hash(length=20))
		return frappe.get_doc(ADMISSION_OFFERING, name).as_dict()
	if status not in {"Draft", "Pending Approval", "Closed", "Retired"}:
		frappe.throw(_("Unsupported Admission Offering status."), frappe.ValidationError)
	doc.check_permission("write")
	doc.status = status
	doc.save()
	return doc.as_dict()


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_admission_offering(name: str, expected_modified: str | None = None) -> dict[str, str]:
	_require_authentication()
	doc = frappe.get_doc(ADMISSION_OFFERING, name)
	doc.check_permission("delete")
	_assert_expected_modified(doc, expected_modified)
	if doc.status == "Active":
		frappe.throw(_("Active offerings must be retired instead of deleted."), frappe.ValidationError)
	doc.delete()
	return {"deleted": name}


@frappe.whitelist()
def list_score_templates(
	search: str | None = None, start: int | str = 0, page_length: int | str = 50
) -> dict[str, Any]:
	_require_authentication()
	result = _paginate(
		SCORE_TEMPLATE, SCORE_TEMPLATE_FIELDS, search, start, page_length, order_by="modified desc, name desc"
	)
	return {"templates": result.pop("rows"), **result}


@frappe.whitelist()
def get_score_template(name: str) -> dict[str, Any]:
	_require_authentication()
	doc = frappe.get_doc(SCORE_TEMPLATE, name)
	doc.check_permission("read")
	return doc.as_dict()


@frappe.whitelist()
def list_score_signals(
	search: str | None = None,
	active_only: bool | str = False,
	start: int | str = 0,
	page_length: int | str = 50,
) -> dict[str, Any]:
	"""List score signals for the rule editor's controlled Signal picker."""
	_require_authentication()
	start, page_length = parse_pagination(start, page_length)
	filters = {}
	if str(active_only).strip().lower() in {"1", "true"}:
		filters["is_active"] = 1

	search_value = _text(search, optional=True)
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [
			[field, "like", like] for field in ("name", "signal_key", "label", "category", "signal_type")
		]

	result = paged_list(
		SCORE_SIGNAL,
		SCORE_SIGNAL_FIELDS,
		filters=filters,
		or_filters=or_filters,
		start=start,
		page_length=page_length,
		order_by="is_active desc, label asc, name asc",
	)
	rows = result.pop("rows")
	return {"signals": [dict(row) for row in rows], **result}


def _score_template_values(values: dict[str, Any]) -> dict[str, Any]:
	allowed = {
		"template_name",
		"status",
		"start_time",
		"end_time",
		"fit_weight",
		"engagement_weight",
		"intent_weight",
		"rules",
	}
	return {key: values[key] for key in allowed if key in values}


@frappe.whitelist(methods=["POST"])
def create_score_template(data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	doc = frappe.new_doc(SCORE_TEMPLATE)
	doc.check_permission("create")
	doc.update(_score_template_values(_parse_data(data, _("Score Template"))))
	doc.insert()
	return doc.as_dict()


@frappe.whitelist(methods=["POST", "PUT"])
def update_score_template(
	name: str, data: dict[str, Any] | str, expected_modified: str | None = None
) -> dict[str, Any]:
	_require_authentication()
	doc = frappe.get_doc(SCORE_TEMPLATE, name)
	doc.check_permission("write")
	_assert_expected_modified(doc, expected_modified)
	doc.update(_score_template_values(_parse_data(data, _("Score Template"))))
	doc.save()
	return doc.as_dict()


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_score_template(name: str, expected_modified: str | None = None) -> dict[str, str]:
	_require_authentication()
	doc = frappe.get_doc(SCORE_TEMPLATE, name)
	doc.check_permission("delete")
	_assert_expected_modified(doc, expected_modified)
	doc.delete()
	return {"deleted": name}


def _governed_payload(doc: Any) -> dict[str, Any]:
	return doc.as_dict()


@frappe.whitelist()
def list_governed_values(
	doctype: str,
	search: str | None = None,
	include_retired: bool | str = False,
	start: int | str = 0,
	page_length: int | str = 50,
) -> dict[str, Any]:
	_require_authentication()
	if doctype not in GOVERNED_FIELDS:
		frappe.throw(_("Unsupported governed catalog."), frappe.ValidationError)
	start, page_length = parse_pagination(start, page_length)
	filters = {} if str(include_retired).lower() in {"1", "true", "yes"} else {"approval_state": "Approved"}
	name_field = GOVERNED_VALUE_FIELDS[doctype]
	search_value = _text(search, optional=True)
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [[field, "like", like] for field in ("name", name_field)]
	result = paged_list(
		doctype,
		GOVERNED_FIELDS[doctype],
		filters=filters,
		or_filters=or_filters,
		start=start,
		page_length=page_length,
		order_by=f"{name_field} asc, name asc",
	)
	rows = result.pop("rows")
	return {"records": [dict(row) for row in rows], **result}


@frappe.whitelist(methods=["POST"])
def create_governed_value(doctype: str, data: dict[str, Any] | str) -> dict[str, Any]:
	_require_authentication()
	if doctype not in GOVERNED_FIELDS:
		frappe.throw(_("Unsupported governed catalog."), frappe.ValidationError)
	values = _parse_data(data, _("Governed catalog value"))
	name_field = GOVERNED_VALUE_FIELDS[doctype]
	value = _text(values.get(name_field))
	if not value:
		frappe.throw(_("A catalog value is required."), frappe.ValidationError)
	result = create_additive_value(
		doctype,
		value,
		reason=_text(values.get("reason"), optional=True),
		idempotency_key=_text(values.get("idempotency_key"), optional=True),
		lead_source=_text(values.get("lead_source"), optional=True),
	)
	return {**result, "record": _governed_payload(frappe.get_doc(doctype, result["name"]))}


@frappe.whitelist(methods=["POST"])
def propose_governed_change(
	doctype: str,
	docname: str,
	action: str,
	reason: str,
	new_value: str | None = None,
	expected_version: int | str | None = None,
) -> dict[str, Any]:
	_require_authentication()
	result = propose_change(
		doctype, docname, action, new_value=new_value, reason=reason, expected_version=expected_version
	)
	return {"change": result}


@frappe.whitelist(methods=["POST"])
def approve_governed_change(change_log_name: str) -> dict[str, Any]:
	_require_authentication()
	return {"status": approve_change(change_log_name)}


@frappe.whitelist()
def list_governed_changes(doctype: str) -> dict[str, Any]:
	_require_authentication()
	if doctype not in GOVERNED_FIELDS:
		frappe.throw(_("Unsupported governed catalog."), frappe.ValidationError)
	return {"changes": list_pending_changes(doctype)}
