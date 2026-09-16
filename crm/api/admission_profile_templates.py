"""Read APIs for the admission method, offering and profile template catalog."""

from __future__ import annotations

import re
from typing import Any

import frappe
from frappe import _

from crm.api._pagination import parse_pagination

SUPPORTED_ADMISSION_METHOD_CODES = ("THPT_SCORE", "COLLEGE_GRADUATION", "DIRECT_ADMISSION")
LEGACY_TEMPLATE_CODES = frozenset({"SPECIAL_PROGRAM", "FPT_POLYTECHNIC"})
TEMPLATE_ADMIN_ROLES = frozenset({"Administrator", "System Manager", "Admissions Director"})
TEMPLATE_STATUSES = frozenset({"Draft", "Active", "Archived"})
TEMPLATE_KINDS = frozenset({"standard", "special"})
TEMPLATE_TRANSITIONS = {
	"Draft": frozenset({"Draft", "Active", "Archived"}),
	"Active": frozenset({"Active", "Archived"}),
	"Archived": frozenset({"Archived"}),
}
TEMPLATE_DATA_FIELDS = frozenset(
	{
		"template_code",
		"template_name",
		"template_kind",
		"profile_type",
		"status",
		"version",
		"education_program",
		"admission_method",
		"description",
		"requirements",
		"document_types",
	}
)
REQUIREMENT_FIELDS = frozenset(
	{
		"section_code",
		"document_type",
		"requirement_group",
		"requirement_mode",
		"is_required",
		"min_required",
		"quantity",
		"order_display",
		"condition_key",
		"instruction",
	}
)


def _as_bool(value: Any) -> bool:
	return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _require_template_admin() -> None:
	user = getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.AuthenticationError)
	if not TEMPLATE_ADMIN_ROLES.intersection(frappe.get_roles(user)):
		frappe.throw(
			_("Only an administrator or Admissions Director can manage profile templates."),
			frappe.PermissionError,
		)


def _parse_object(value: dict[str, Any] | str | None, label: str) -> dict[str, Any]:
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			value = None
	if not isinstance(value, dict):
		frappe.throw(_("{0} must be an object.").format(label), frappe.ValidationError)
	return value


def _as_positive_int(value: Any, fieldname: str, *, default: int = 1) -> int:
	try:
		parsed = int(value if value not in (None, "") else default)
	except (TypeError, ValueError):
		frappe.throw(_("{0} must be a positive integer.").format(fieldname), frappe.ValidationError)
	if parsed < 1:
		frappe.throw(_("{0} must be a positive integer.").format(fieldname), frappe.ValidationError)
	return parsed


def _document_type_rows(
	*,
	include_archived: bool = False,
	active_only: bool = False,
	search: str | None = None,
	ignore_permissions: bool = True,
) -> list[Any]:
	filters = {"status": ["in", ["Active", "Archived"]] if include_archived else "Active"}
	if active_only:
		filters["is_active"] = 1
	search_value = str(search or "").strip()
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [[fieldname, "like", like] for fieldname in ("name", "code", "label", "category")]
	return frappe.get_all(
		"CRM Document Type",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "code", "label", "category", "description", "status", "is_active"],
		order_by="label asc, name asc",
		limit_page_length=0,
		ignore_permissions=ignore_permissions,
	)


def _document_type_lookup(*, include_archived: bool = False) -> dict[str, Any]:
	lookup = {}
	for row in _document_type_rows(include_archived=include_archived):
		lookup[row.name] = row
		if row.code:
			lookup[row.code] = row
	return lookup


def _resolve_document_type(reference: Any, lookup: dict[str, Any]) -> str:
	value = str(reference or "").strip()
	row = lookup.get(value)
	if not row or row.status != "Active" or not int(row.is_active or 0):
		frappe.throw(
			_("Document Type {0} must be active before assignment.").format(value or _("is empty")),
			frappe.ValidationError,
		)
	return row.name


def _normalize_requirements(raw_requirements: Any) -> list[dict[str, Any]]:
	if raw_requirements is None:
		raw_requirements = []
	if not isinstance(raw_requirements, list):
		frappe.throw(_("Requirements must be a list."), frappe.ValidationError)

	document_lookup = _document_type_lookup()
	rows = []
	seen_documents = set()
	seen_orders = set()
	groups: dict[str, dict[str, Any]] = {}
	for raw_row in raw_requirements:
		row = _parse_object(raw_row, _("Requirement"))
		unknown = set(row) - (
			REQUIREMENT_FIELDS
			| {
				"documentType",
				"sectionCode",
				"requirementGroup",
				"requirementMode",
				"isRequired",
				"minimumRequired",
				"orderDisplay",
				"conditionKey",
			}
		)
		if unknown:
			frappe.throw(
				_("Unsupported requirement fields: {0}.").format(", ".join(sorted(unknown))),
				frappe.ValidationError,
			)
		document_reference = row.get("document_type") or row.get("documentType")
		document_type = _resolve_document_type(document_reference, document_lookup)
		if document_type in seen_documents:
			frappe.throw(
				_("Document Type {0} is duplicated in the template.").format(document_reference),
				frappe.ValidationError,
			)
		seen_documents.add(document_type)
		section_code = str(row.get("section_code") or row.get("sectionCode") or "general").strip()
		group_name = str(
			row.get("requirement_group") or row.get("requirementGroup") or f"document:{document_type}"
		).strip()
		mode = str(row.get("requirement_mode") or row.get("requirementMode") or "ALL").strip().upper()
		if not section_code or not group_name:
			frappe.throw(_("Section Code and Requirement Group are required."), frappe.ValidationError)
		if mode not in {"ALL", "ANY"}:
			frappe.throw(_("Requirement Mode must be ALL or ANY."), frappe.ValidationError)
		required_value = row.get("is_required", row.get("isRequired", 1))
		is_required = 1 if _as_bool(required_value) else 0
		min_required = _as_positive_int(
			row.get("min_required", row.get("minimumRequired")),
			"min_required",
		)
		quantity = _as_positive_int(row.get("quantity"), "quantity")
		order_display = _as_positive_int(
			row.get("order_display", row.get("orderDisplay")),
			"order_display",
		)
		if order_display in seen_orders:
			frappe.throw(_("order_display values must be unique within a template."), frappe.ValidationError)
		seen_orders.add(order_display)
		if mode == "ANY" and quantity != 1:
			frappe.throw(_("ANY requirements must use quantity 1."), frappe.ValidationError)
		condition_key = row.get("condition_key", row.get("conditionKey"))
		instruction = row.get("instruction")
		group = groups.setdefault(
			group_name,
			{
				"section_code": section_code,
				"requirement_mode": mode,
				"is_required": is_required,
				"min_required": min_required,
				"rows": [],
			},
		)
		if any(
			(
				group[fieldname] != expected
				for fieldname, expected in (
					("section_code", section_code),
					("requirement_mode", mode),
					("is_required", is_required),
					("min_required", min_required),
				)
			)
		):
			frappe.throw(
				_("Rows in one requirement group must share section, mode and required settings."),
				frappe.ValidationError,
			)
		group["rows"].append(document_type)
		rows.append(
			{
				"doctype": "CRM Profile Template Document Type",
				"section_code": section_code,
				"document_type": document_type,
				"requirement_group": group_name,
				"requirement_mode": mode,
				"is_required": is_required,
				"min_required": min_required,
				"quantity": quantity,
				"order_display": order_display,
				"condition_key": str(condition_key or "").strip() or None,
				"instruction": str(instruction or "").strip() or None,
			}
		)
	for group_name, group in groups.items():
		if group["requirement_mode"] == "ANY" and group["min_required"] > len(group["rows"]):
			frappe.throw(
				_("Requirement group {0} has min_required greater than its alternatives.").format(group_name),
				frappe.ValidationError,
			)
	return sorted(rows, key=lambda row: (row["order_display"], row["document_type"]))


def _normalize_template_data(data: dict[str, Any], *, is_create: bool) -> dict[str, Any]:
	unknown = set(data) - TEMPLATE_DATA_FIELDS
	if unknown:
		frappe.throw(
			_("Unsupported template fields: {0}.").format(", ".join(sorted(unknown))),
			frappe.ValidationError,
		)
	code = str(data.get("template_code") or "").strip().upper()
	name = str(data.get("template_name") or "").strip()
	if is_create and (not code or not re.fullmatch(r"[A-Z][A-Z0-9_]*", code)):
		frappe.throw(
			_("Template Code must use uppercase letters, digits and underscores."), frappe.ValidationError
		)
	if is_create and not name:
		frappe.throw(_("Template Name is required."), frappe.ValidationError)
	status = str(data.get("status") or "Draft").strip().title()
	if status not in TEMPLATE_STATUSES:
		frappe.throw(_("Template status is invalid."), frappe.ValidationError)
	profile_type = str(data.get("profile_type") or "academic_admission").strip()
	if profile_type != "academic_admission":
		frappe.throw(_("Only academic admission templates can be managed here."), frappe.ValidationError)
	template_kind = str(data.get("template_kind") or "standard").strip().lower()
	if template_kind not in TEMPLATE_KINDS:
		frappe.throw(_("Template kind is invalid."), frappe.ValidationError)
	version = _as_positive_int(data.get("version"), "version")
	method = data.get("admission_method")
	if method:
		method = (
			frappe.db.get_value("CRM Admission Method", {"code": str(method).strip()}, "name")
			or str(method).strip()
		)
		if not frappe.db.exists("CRM Admission Method", method):
			frappe.throw(_("Admission Method {0} does not exist.").format(method), frappe.ValidationError)
	requirements = data.get("requirements", data.get("document_types", []))
	return {
		"template_code": code,
		"template_name": name,
		"template_kind": template_kind,
		"profile_type": profile_type,
		"status": status,
		"version": version,
		"education_program": data.get("education_program") or None,
		"admission_method": method or None,
		"description": str(data.get("description") or "").strip() or None,
		"document_types": _normalize_requirements(requirements),
	}


def _assert_admission_method_enabled(method: str | None, status: str) -> None:
	if not method or status != "Active":
		return
	if not frappe.db.get_value("CRM Admission Method", method, "enabled"):
		frappe.throw(
			_("An active template must use an enabled Admission Method."),
			frappe.ValidationError,
		)


def _assert_expected_modified(doc, expected_modified: str | None) -> None:
	if expected_modified and str(doc.modified) != str(expected_modified):
		frappe.throw(
			_("Template đã được cập nhật bởi người khác. Vui lòng tải lại rồi thử lại."),
			frappe.ValidationError,
		)


def _assert_template_kind_immutable(doc, template_kind: str) -> None:
	current_kind = str(doc.template_kind or "standard").strip().lower()
	if template_kind != current_kind:
		frappe.throw(
			_("Không thể thay đổi nhóm của loại hồ sơ sau khi đã tạo."),
			frappe.ValidationError,
		)


def _assert_template_not_in_use(doc) -> None:
	for doctype in ("CRM Admission Application", "CRM Student Admission Profile"):
		if frappe.db.exists(doctype, {"profile_template": doc.name}):
			frappe.throw(
				_("Template {0} is already used by {1}; archive it instead.").format(
					doc.template_code, doctype
				),
				frappe.ValidationError,
			)

	if frappe.db.exists(
		"CRM Admission Application Special Profile",
		{"special_profile_template": ["in", [doc.name, doc.template_code]]},
	):
		frappe.throw(
			_("Template {0} is already selected in an admission application; archive it instead.").format(
				doc.template_code
			),
			frappe.ValidationError,
		)


def _template_payload(doc, document_types: dict[str, Any] | None = None) -> dict[str, Any]:
	document_types = document_types or {row.name: row for row in _document_type_rows(include_archived=True)}
	return {
		"id": doc.name,
		"code": doc.template_code,
		"name": doc.template_name,
		"templateKind": doc.template_kind or "standard",
		"profileType": doc.profile_type,
		"status": doc.status,
		"version": int(doc.version or 1),
		"educationProgram": doc.education_program,
		"admissionMethod": doc.admission_method,
		"description": doc.description,
		"modified": str(doc.modified) if doc.modified else None,
		"requirements": [_requirement(row, document_types) for row in doc.get("document_types") or []],
	}


def _requirement(row, document_types: dict[str, Any]) -> dict[str, Any]:
	document_type = str(row.get("document_type") or "").strip()
	descriptor = document_types.get(document_type, frappe._dict())
	return {
		"sectionCode": row.get("section_code") or "general",
		"documentType": document_type,
		"documentCode": descriptor.get("code") or document_type,
		"documentLabel": descriptor.get("label") or document_type,
		"category": descriptor.get("category"),
		"description": descriptor.get("description"),
		"requirementGroup": row.get("requirement_group") or f"document:{document_type}",
		"requirementMode": str(row.get("requirement_mode") or "ALL").upper(),
		"isRequired": _as_bool(row.get("is_required")),
		"minimumRequired": int(row.get("min_required") or 1),
		"quantity": int(row.get("quantity") or 1),
		"orderDisplay": int(row.get("order_display") or 0),
		"conditionKey": row.get("condition_key"),
		"instruction": row.get("instruction"),
	}


def _offering_label(row, method_labels: dict[str, str], year_labels: dict[str, str]) -> str:
	year = year_labels.get(row.admission_year) or row.admission_year
	method = method_labels.get(row.admission_method) or row.admission_method
	parts = [year, row.campus, row.major, method]
	return " · ".join(str(part) for part in parts if part)


@frappe.whitelist()
def get_admission_profile_catalog(
	admission_year: str | None = None, search: str | None = None
) -> dict[str, Any]:
	"""Return the active catalog needed to create a Student admission profile."""
	method_rows = frappe.get_list(
		"CRM Admission Method",
		filters={
			"enabled": 1,
			"code": ["in", list(SUPPORTED_ADMISSION_METHOD_CODES)],
		},
		fields=["name", "code", "display_name", "description", "sort_order", "enabled"],
		order_by="sort_order asc, display_name asc",
		limit_page_length=0,
	)
	methods = [
		{
			"id": row.name,
			"code": row.code or row.name,
			"name": row.display_name or row.name,
			"description": row.description,
			"sortOrder": int(row.sort_order or 0),
		}
		for row in method_rows
		if row.code in SUPPORTED_ADMISSION_METHOD_CODES
	]
	method_labels = {item["id"]: item["name"] for item in methods}
	method_labels.update({item["code"]: item["name"] for item in methods})

	year_filters = {"is_active": 1}
	if admission_year:
		year_filters["name"] = admission_year
	year_rows = frappe.get_list(
		"CRM Admission Year",
		filters=year_filters,
		fields=["name", "year_name", "is_active", "start_date", "end_date"],
		order_by="year_name desc",
		limit_page_length=0,
	)
	years = [
		{
			"id": row.name,
			"name": row.year_name or row.name,
			"isActive": _as_bool(row.is_active),
			"startDate": row.start_date,
			"endDate": row.end_date,
		}
		for row in year_rows
	]
	year_labels = {item["id"]: item["name"] for item in years}

	all_document_rows = _document_type_rows(active_only=True, ignore_permissions=False)
	document_rows = (
		_document_type_rows(active_only=True, search=search, ignore_permissions=False)
		if str(search or "").strip()
		else all_document_rows
	)
	document_types = {row.name: row for row in all_document_rows}

	template_rows = frappe.get_list(
		"CRM Admission Profile Template",
		filters={"status": "Active", "profile_type": "academic_admission"},
		fields=[
			"name",
			"template_code",
			"template_name",
			"template_kind",
			"profile_type",
			"status",
			"version",
			"education_program",
			"admission_method",
			"description",
		],
		order_by="template_code asc, version desc",
		limit_page_length=0,
	)
	templates = []
	special_templates = []
	for row in template_rows:
		if row.template_code in LEGACY_TEMPLATE_CODES:
			continue
		template_doc = frappe.get_doc("CRM Admission Profile Template", row.name)
		payload = _template_payload(template_doc, document_types)
		if (row.template_kind or "standard") == "special":
			special_templates.append(payload)
		else:
			templates.append(payload)

	offering_filters = {"status": "Active"}
	if admission_year:
		offering_filters["admission_year"] = admission_year
	offering_rows = frappe.get_list(
		"CRM Admission Offering",
		filters=offering_filters,
		fields=[
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
		],
		order_by="admission_year desc, effective_from desc, name asc",
		limit_page_length=0,
	)
	offerings = [
		{
			"id": row.name,
			"offeringKey": row.offering_key,
			"admissionYear": row.admission_year,
			"admissionYearName": year_labels.get(row.admission_year) or row.admission_year,
			"campus": row.campus,
			"major": row.major,
			"admissionMethod": row.admission_method,
			"admissionMethodName": method_labels.get(row.admission_method) or row.admission_method,
			"quota": int(row.quota or 0),
			"effectiveFrom": row.effective_from,
			"effectiveUntil": row.effective_until,
			"status": row.status,
			"label": _offering_label(row, method_labels, year_labels),
		}
		for row in offering_rows
	]

	return {
		"methods": methods,
		"years": years,
		"offerings": offerings,
		"documentTypes": [
			{
				"id": row.name,
				"code": row.code,
				"name": row.label,
				"category": row.category,
				"description": row.description,
			}
			for row in document_rows
		],
		"templates": templates,
		"specialTemplates": special_templates,
	}


@frappe.whitelist()
def list_admission_profile_templates(
	status: str | None = None,
	search: str | None = None,
	template_kind: str | None = None,
	start: int | str | None = None,
	page_length: int | str | None = None,
) -> dict[str, Any]:
	"""Return all academic templates and active document types for admin CRUD."""
	_require_template_admin()
	is_paginated = start not in (None, "") or page_length not in (None, "")
	if is_paginated:
		start_value, template_page_length = parse_pagination(start, page_length)
	status_value = str(status or "").strip().title()
	filters = {"profile_type": "academic_admission"}
	if status_value:
		if status_value not in TEMPLATE_STATUSES:
			frappe.throw(_("Template status is invalid."), frappe.ValidationError)
		filters["status"] = status_value
	template_kind_value = str(template_kind or "").strip().lower()
	if template_kind_value:
		if template_kind_value not in {"standard", "special"}:
			frappe.throw(_("Template kind is invalid."), frappe.ValidationError)
		filters["template_kind"] = template_kind_value
	filters["template_code"] = ["not in", list(LEGACY_TEMPLATE_CODES)]
	search_value = str(search or "").strip()
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [
			[fieldname, "like", like]
			for fieldname in ("name", "template_code", "template_name", "description")
		]
	all_document_rows = _document_type_rows()
	# The template list is paginated independently; keep the complete document
	# type catalogue available to create/edit forms even while searching templates.
	document_rows = (
		all_document_rows
		if is_paginated
		else (_document_type_rows(search=search) if search_value else all_document_rows)
	)
	document_types = {row.name: row for row in all_document_rows}
	list_kwargs = {
		"filters": filters,
		"or_filters": or_filters,
		"fields": ["name", "template_code"],
		"order_by": "status asc, template_code asc, version desc, name asc",
		"ignore_permissions": True,
	}
	if is_paginated:
		list_kwargs.update(start=start_value, page_length=template_page_length)
	else:
		list_kwargs["limit_page_length"] = 0
	rows = frappe.get_all("CRM Admission Profile Template", **list_kwargs)
	response = {
		"templates": [
			_template_payload(frappe.get_doc("CRM Admission Profile Template", row.name), document_types)
			for row in rows
		],
		"documentTypes": [
			{
				"id": row.name,
				"code": row.code,
				"name": row.label,
				"category": row.category,
				"description": row.description,
			}
			for row in document_rows
		],
	}
	if is_paginated:
		total_rows = frappe.get_all(
			"CRM Admission Profile Template",
			filters=filters,
			or_filters=or_filters,
			fields=["count(name) as total"],
			limit_page_length=0,
			ignore_permissions=True,
		)
		response.update(
			total=int((total_rows[0].get("total") if total_rows else 0) or 0),
			start=start_value,
			page_length=template_page_length,
		)
	return response


@frappe.whitelist(methods=["POST"])
def create_admission_profile_template(data: dict[str, Any] | str) -> dict[str, Any]:
	"""Create one academic profile template for the admin catalog."""
	_require_template_admin()
	values = _normalize_template_data(_parse_object(data, _("Template")), is_create=True)
	_assert_admission_method_enabled(values["admission_method"], values["status"])
	if frappe.db.exists("CRM Admission Profile Template", {"template_code": values["template_code"]}):
		frappe.throw(
			_("Template Code {0} already exists.").format(values["template_code"]),
			frappe.DuplicateEntryError,
		)
	if values["status"] == "Active" and not values["document_types"]:
		frappe.throw(_("An active template must contain at least one requirement."), frappe.ValidationError)
	doc = frappe.get_doc({"doctype": "CRM Admission Profile Template", **values})
	doc.insert(ignore_permissions=True)
	return _template_payload(doc)


@frappe.whitelist(methods=["POST"])
def update_admission_profile_template(
	name: str, data: dict[str, Any] | str, expected_modified: str | None = None
) -> dict[str, Any]:
	"""Update template metadata and its document requirement rows."""
	_require_template_admin()
	doc = frappe.get_doc("CRM Admission Profile Template", str(name or "").strip())
	_assert_expected_modified(doc, expected_modified)
	data_object = _parse_object(data, _("Template"))
	data_object.setdefault("template_kind", doc.template_kind or "standard")
	values = _normalize_template_data(data_object, is_create=False)
	_assert_admission_method_enabled(values["admission_method"], values["status"])
	if values["template_code"] and values["template_code"] != doc.template_code:
		frappe.throw(_("Template Code is immutable."), frappe.PermissionError)
	_assert_template_kind_immutable(doc, values["template_kind"])
	if values["status"] not in TEMPLATE_TRANSITIONS.get(doc.status, frozenset()):
		frappe.throw(_("Invalid template status transition."), frappe.ValidationError)
	if values["status"] == "Active" and not values["document_types"]:
		frappe.throw(_("An active template must contain at least one requirement."), frappe.ValidationError)
	for fieldname in (
		"template_name",
		"template_kind",
		"profile_type",
		"status",
		"version",
		"education_program",
		"admission_method",
		"description",
		"document_types",
	):
		doc.set(fieldname, values[fieldname])
	previous_flag = getattr(frappe.flags, "admission_profile_template_admin_update", False)
	frappe.flags.admission_profile_template_admin_update = True
	try:
		doc.save(ignore_permissions=True)
	finally:
		frappe.flags.admission_profile_template_admin_update = previous_flag
	return _template_payload(doc)


@frappe.whitelist(methods=["POST"])
def transition_admission_profile_template(
	name: str, status: str, expected_modified: str | None = None
) -> dict[str, Any]:
	"""Move a template through Draft, Active and Archived states."""
	_require_template_admin()
	doc = frappe.get_doc("CRM Admission Profile Template", str(name or "").strip())
	_assert_expected_modified(doc, expected_modified)
	status_value = str(status or "").strip().title()
	if status_value not in TEMPLATE_STATUSES:
		frappe.throw(_("Template status is invalid."), frappe.ValidationError)
	if status_value not in TEMPLATE_TRANSITIONS.get(doc.status, frozenset()):
		frappe.throw(_("Invalid template status transition."), frappe.ValidationError)
	_assert_admission_method_enabled(doc.get("admission_method"), status_value)
	if status_value == "Active" and not doc.get("document_types"):
		frappe.throw(_("An active template must contain at least one requirement."), frappe.ValidationError)
	doc.status = status_value
	previous_flag = getattr(frappe.flags, "admission_profile_template_admin_update", False)
	frappe.flags.admission_profile_template_admin_update = True
	try:
		doc.save(ignore_permissions=True)
	finally:
		frappe.flags.admission_profile_template_admin_update = previous_flag
	return _template_payload(doc)


@frappe.whitelist(methods=["POST"])
def delete_admission_profile_template(name: str, expected_modified: str | None = None) -> dict[str, Any]:
	"""Delete only an unused Draft template; archive active policies instead."""
	_require_template_admin()
	doc = frappe.get_doc("CRM Admission Profile Template", str(name or "").strip())
	_assert_expected_modified(doc, expected_modified)
	if doc.status != "Draft":
		frappe.throw(
			_("Only Draft templates can be deleted. Archive an active template instead."),
			frappe.ValidationError,
		)
	_assert_template_not_in_use(doc)
	frappe.delete_doc("CRM Admission Profile Template", doc.name, ignore_permissions=True)
	return {"name": doc.name, "deleted": True}
