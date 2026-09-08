"""APIs for Student and High School records and their form options."""

from __future__ import annotations

import frappe
from frappe import _

from crm.api.lead_mapping import _normalize_lead_payload
from crm.fcrm.role_policy import resolve_crm_profile

_STUDENT_BASIC_FIELDS = frozenset(
	{
		"student_name",
		"phone",
		"email",
		"other_email",
		"gender",
		"date_of_birth",
		"province",
		"ward",
		"high_school",
		"current_grade",
		"study_stage",
		"branch",
		"major",
		"aspiration",
		"advertising_channel",
		"conversion_potential",
		"segments",
		"admission_year",
		"alt_name",
		"alt_phone",
		"alt_address",
		"notes",
		"id_number",
		"id_issued_date",
		"id_issued_place",
	}
)
_STUDENT_WITH_LEAD_FIELDS = _STUDENT_BASIC_FIELDS | {
	"source",
	"assigned_to",
	"description",
	"campaign_code",
}

_SCHOOL_BASIC_FIELDS = frozenset(
	{
		"school_name",
		"school_type",
		"school_area",
		"school_tier",
		"boarding_type",
		"province",
		"ward",
		"latitude",
		"longitude",
		"address",
		"phone",
		"email",
	}
)
_SCHOOL_CREATE_FIELDS = _SCHOOL_BASIC_FIELDS | {"school_code"}
_OPTION_DOCTYPES = frozenset({"CRM Lead", "CRM High School"})
_OPTION_FIELD_TYPES = frozenset({"Link", "Select"})
_DEFAULT_OPTION_LIMIT = 20
_MAX_OPTION_LIMIT = 100
_CTV_STUDENT_UPDATE_FIELDS = frozenset({"notes"})


def _parse_fields(fields: dict | str | None, allowed_fields: frozenset[str]) -> dict:
	if isinstance(fields, str):
		try:
			fields = frappe.parse_json(fields)
		except (TypeError, ValueError):
			frappe.throw(_("fields must be a valid JSON object."), frappe.ValidationError)

	if not isinstance(fields, dict) or not fields:
		frappe.throw(_("fields must be a non-empty object."), frappe.ValidationError)

	unknown_fields = [field for field in fields if field not in allowed_fields]
	if unknown_fields:
		frappe.throw(
			_("These fields are not allowed: {0}.").format(", ".join(map(str, unknown_fields))),
			frappe.ValidationError,
		)

	return fields


def _validate_required_fields(fields: dict, required_fields: frozenset[str]) -> None:
	missing_fields = [
		fieldname
		for fieldname in required_fields
		if fields.get(fieldname) is None
		or (isinstance(fields.get(fieldname), str) and not fields[fieldname].strip())
	]
	if missing_fields:
		frappe.throw(
			_("These fields are required: {0}.").format(", ".join(sorted(missing_fields))),
			frappe.ValidationError,
		)


def _update_document(doctype: str, name: str, fields: dict, allowed_fields: frozenset[str]) -> dict:
	if not isinstance(name, str) or not name.strip():
		frappe.throw(_("Document name is required."), frappe.ValidationError)

	values = _parse_fields(fields, allowed_fields)
	actor = getattr(getattr(frappe, "session", None), "user", None)
	profile = (
		resolve_crm_profile(frappe.get_roles(actor))
		if actor not in {None, "Guest", "None", "Administrator"}
		else None
	)
	if doctype == "CRM Lead" and profile == "ctv_sale":
		unauthorized_fields = set(values) - _CTV_STUDENT_UPDATE_FIELDS
		if unauthorized_fields:
			frappe.throw(
				_("CTV Sale may only update: {0}.").format(", ".join(sorted(_CTV_STUDENT_UPDATE_FIELDS))),
				frappe.PermissionError,
			)
	doc = frappe.get_doc(doctype, name.strip())
	doc.check_permission("write")

	for fieldname, value in values.items():
		doc.set(fieldname, value)

	doc.save()
	return {
		"doctype": doctype,
		"name": doc.name,
		"updated_fields": {fieldname: doc.get(fieldname) for fieldname in values},
	}


def _create_document(
	doctype: str,
	fields: dict | str | None,
	allowed_fields: frozenset[str],
	required_fields: frozenset[str],
) -> dict:
	values = _parse_fields(fields, allowed_fields)
	_validate_required_fields(values, required_fields)

	doc = frappe.new_doc(doctype)
	doc.check_permission("create")
	for fieldname, value in values.items():
		doc.set(fieldname, value)

	doc.insert()
	return {
		"doctype": doctype,
		"name": doc.name,
		"created_fields": {fieldname: doc.get(fieldname) for fieldname in values},
	}


def _delete_document(doctype: str, name: str) -> dict:
	if not isinstance(name, str) or not name.strip():
		frappe.throw(_("Document name is required."), frappe.ValidationError)

	doc = frappe.get_doc(doctype, name.strip())
	doc.check_permission("delete")
	frappe.delete_doc(doctype, doc.name)
	return {"doctype": doctype, "name": doc.name, "deleted": True}


def _student_values_from_lead(values: dict, source_lead: str, lead_code: str | None) -> dict:
	student_fields = {field.fieldname for field in frappe.get_meta("CRM Student").fields}
	student_values = {"doctype": "CRM Student", "source_lead": source_lead}
	if lead_code and "lead_code" in student_fields:
		student_values["lead_code"] = lead_code
	for fieldname, value in values.items():
		student_field = "full_name" if fieldname == "student_name" else fieldname
		if student_field in student_fields and value not in (None, ""):
			student_values[student_field] = value
	return student_values


def _create_student_with_lead(fields: dict | str | None) -> dict:
	values = _parse_fields(fields, _STUDENT_WITH_LEAD_FIELDS)
	lead_values, _tags, _events, assigned_user = _normalize_lead_payload(values)
	converted_at = frappe.utils.now_datetime()

	lead = frappe.get_doc({"doctype": "CRM Lead", **lead_values})
	lead.check_permission("create")

	savepoint = f"create_student_with_lead_{frappe.generate_hash(length=8)}"
	frappe.db.savepoint(savepoint)
	try:
		lead.insert()
		student_values = _student_values_from_lead(lead_values, lead.name, lead.get("lead_code"))
		student_values.update({"student_stage": "New", "converted_at": converted_at})
		student = frappe.get_doc(student_values)
		student.check_permission("create")
		student.insert()
		lead_updates = {
			"student": student.name,
			"converted_student": student.name,
			"converted_at": converted_at,
			"processing_status": "CLOSED",
			"resolution": "CREATED",
			"resolution_reason": "CREATED handoff completed.",
		}
		for fieldname, value in lead_updates.items():
			lead.set(fieldname, value)
		frappe.db.set_value(
			"CRM Lead",
			lead.name,
			lead_updates,
			update_modified=False,
		)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise

	return {
		"doctype": "CRM Student",
		"name": student.name,
		"student": {
			"doctype": "CRM Student",
			"name": student.name,
			"student_stage": student.get("student_stage") or "New",
			"source_lead": lead.name,
		},
		"lead": {
			"doctype": "CRM Lead",
			"name": lead.name,
			"processing_status": "CLOSED",
			"resolution": "CREATED",
			"student": student.name,
		},
		"created_fields": {
			fieldname: student.get(fieldname)
			for fieldname in (
				"full_name",
				"phone",
				"email",
				"province",
				"ward",
				"student_stage",
				"source_lead",
			)
			if student.get(fieldname) not in (None, "")
		},
		"assigned_to_user": assigned_user,
	}


def _get_list_view_fields(doctype: str) -> list[str]:
	return [
		field.fieldname for field in frappe.get_meta(doctype).fields if field.fieldname and field.in_list_view
	]


def _get_list_view_fields_from_meta(meta) -> list[str]:
	return [field.fieldname for field in meta.fields if field.fieldname and field.in_list_view]


def _get_document(doctype: str, name: str) -> dict:
	if not isinstance(name, str) or not name.strip():
		frappe.throw(_("Document name is required."), frappe.ValidationError)

	doc = frappe.get_doc(doctype, name.strip())
	doc.check_permission("read")
	fieldnames = _get_list_view_fields(doctype)
	return {
		"doctype": doctype,
		"name": doc.name,
		"fields": {fieldname: doc.get(fieldname) for fieldname in fieldnames},
	}


def _find_meta_field(meta, fieldname: str):
	return next((field for field in meta.fields if field.fieldname == fieldname), None)


def _parse_option_filters(filters: dict | str | None) -> dict:
	if filters in (None, ""):
		return {}

	if isinstance(filters, str):
		try:
			filters = frappe.parse_json(filters)
		except (TypeError, ValueError):
			frappe.throw(_("filters must be a valid JSON object."), frappe.ValidationError)

	if not isinstance(filters, dict):
		frappe.throw(_("filters must be an object."), frappe.ValidationError)

	for fieldname, value in filters.items():
		if not isinstance(fieldname, str) or not fieldname.strip():
			frappe.throw(_("Filter field names must be non-empty strings."), frappe.ValidationError)
		if isinstance(value, (dict, list, tuple, set)):
			frappe.throw(_("Only scalar values are supported in option filters."), frappe.ValidationError)

	return filters


def _parse_option_limit(limit: int | str | None) -> int:
	if limit in (None, ""):
		return _DEFAULT_OPTION_LIMIT

	try:
		parsed_limit = int(limit)
	except (TypeError, ValueError):
		frappe.throw(_("limit must be an integer."), frappe.ValidationError)

	if parsed_limit < 1 or parsed_limit > _MAX_OPTION_LIMIT:
		frappe.throw(_("limit must be between 1 and {0}.").format(_MAX_OPTION_LIMIT), frappe.ValidationError)

	return parsed_limit


def _get_select_options(field, search: str | None, limit: int) -> list[dict]:
	values = [value.strip() for value in (field.options or "").splitlines() if value.strip()]
	if search:
		query = search.casefold()
		values = [value for value in values if query in value.casefold()]

	return [{"value": value, "label": value} for value in values[:limit]]


def _get_link_options(
	target_doctype: str,
	filters: dict,
	search: str | None,
	limit: int,
	target_meta=None,
) -> list[dict]:
	target_meta = target_meta or frappe.get_meta(target_doctype)
	filter_fields = {field.fieldname for field in target_meta.fields if field.fieldname}
	unknown_filters = [fieldname for fieldname in filters if fieldname not in filter_fields]
	if unknown_filters:
		frappe.throw(
			_("These option filter fields are not available: {0}.").format(
				", ".join(sorted(unknown_filters))
			),
			frappe.ValidationError,
		)

	title_field = target_meta.title_field if getattr(target_meta, "title_field", None) else "name"
	if title_field != "name" and title_field not in filter_fields:
		title_field = "name"

	fields = ["name"] if title_field == "name" else ["name", title_field]
	or_filters = None
	if search:
		or_filters = [["name", "like", f"%{search}%"]]
		if title_field != "name":
			or_filters.append([title_field, "like", f"%{search}%"])

	rows = frappe.get_list(
		target_doctype,
		filters=filters,
		or_filters=or_filters,
		fields=fields,
		order_by=f"{title_field} asc, name asc",
		limit_page_length=limit,
	)
	return [
		{
			"value": row.get("name"),
			"label": row.get(title_field) or row.get("name"),
		}
		for row in rows
	]


@frappe.whitelist(methods=["POST"])
def create_student(fields: dict | str | None = None) -> dict:
	"""Legacy route that creates a CRM Lead; use create_student_with_lead for a real Student."""
	return _create_document(
		"CRM Lead",
		fields,
		_STUDENT_BASIC_FIELDS,
		{"student_name"},
	)


@frappe.whitelist(methods=["POST"])
def create_student_with_lead(fields: dict | str | None = None) -> dict:
	"""Create a real CRM Student and its linked source CRM Lead atomically."""
	return _create_student_with_lead(fields)


@frappe.whitelist(methods=["POST"])
def create_school(fields: dict | str | None = None) -> dict:
	"""Create a CRM High School with basic profile and identity fields."""
	return _create_document(
		"CRM High School",
		fields,
		_SCHOOL_CREATE_FIELDS,
		{"school_name", "school_code", "province", "ward"},
	)


@frappe.whitelist(methods=["GET"])
def get_student(name: str) -> dict:
	"""Get one Student with the fields marked ``in_list_view`` in its DocType."""
	return _get_document("CRM Lead", name)


@frappe.whitelist(methods=["GET"])
def get_school(name: str) -> dict:
	"""Get one High School with the fields marked ``in_list_view`` in its DocType."""
	return _get_document("CRM High School", name)


def _parse_text_filter(value: str | None, fieldname: str) -> str | None:
	if value is None:
		return None
	if not isinstance(value, str):
		frappe.throw(_("{0} must be a string.").format(fieldname), frappe.ValidationError)
	value = value.strip()
	return value or None


@frappe.whitelist(methods=["GET"])
def get_schools(
	province: str | None = None,
	ward: str | None = None,
	search: str | None = None,
	limit: int | str | None = None,
) -> dict:
	"""List High Schools with optional province, ward, and text filters."""
	province = _parse_text_filter(province, "province")
	ward = _parse_text_filter(ward, "ward")
	search = _parse_text_filter(search, "search")
	parsed_limit = _parse_option_limit(limit)

	meta = frappe.get_meta("CRM High School")
	list_fields = _get_list_view_fields_from_meta(meta)
	query_fields = ["name", *[fieldname for fieldname in list_fields if fieldname != "name"]]
	filters = {fieldname: value for fieldname, value in {"province": province, "ward": ward}.items() if value}
	search_fields = [
		fieldname
		for fieldname in ("school_name", "school_code")
		if _find_meta_field(meta, fieldname) is not None
	]
	or_filters = [[fieldname, "like", f"%{search}%"] for fieldname in search_fields] if search else None
	rows = frappe.get_list(
		"CRM High School",
		filters=filters,
		or_filters=or_filters,
		fields=query_fields,
		order_by="school_name asc, name asc",
		limit_page_length=parsed_limit,
	)

	return {
		"doctype": "CRM High School",
		"filters": {**filters, **({"search": search} if search else {})},
		"schools": [
			{
				"name": row.get("name"),
				"fields": {fieldname: row.get(fieldname) for fieldname in list_fields},
			}
			for row in rows
		],
	}


@frappe.whitelist(methods=["GET"])
def get_field_options(
	doctype: str,
	fieldname: str,
	search: str | None = None,
	filters: dict | str | None = None,
	limit: int | str | None = None,
	province: str | None = None,
) -> dict:
	"""Get options for any Link or Select field on Student or High School."""
	if doctype not in _OPTION_DOCTYPES:
		frappe.throw(_("Options are not available for this doctype."), frappe.ValidationError)
	if not isinstance(fieldname, str) or not fieldname.strip():
		frappe.throw(_("fieldname is required."), frappe.ValidationError)
	if search is not None and not isinstance(search, str):
		frappe.throw(_("search must be a string."), frappe.ValidationError)

	fieldname = fieldname.strip()
	meta = frappe.get_meta(doctype)
	field = _find_meta_field(meta, fieldname)
	if field is None:
		frappe.throw(_("Field {0} does not exist on {1}.").format(fieldname, doctype), frappe.ValidationError)
	if field.fieldtype not in _OPTION_FIELD_TYPES:
		frappe.throw(_("Field {0} is not a Link or Select field.").format(fieldname), frappe.ValidationError)

	parsed_filters = _parse_option_filters(filters)
	parsed_limit = _parse_option_limit(limit)
	search = search.strip() if search else None
	province = _parse_text_filter(province, "province")

	if field.fieldtype == "Select":
		if province:
			frappe.throw(_("province can only be used with a Link field."), frappe.ValidationError)
		options = _get_select_options(field, search, parsed_limit)
		target_doctype = None
	else:
		target_doctype = (field.options or "").strip()
		if not target_doctype:
			frappe.throw(_("Link field {0} has no target doctype.").format(fieldname), frappe.ValidationError)
		target_meta = frappe.get_meta(target_doctype) if province else None
		if province:
			if _find_meta_field(target_meta, "province") is None:
				frappe.throw(
					_("province cannot be used to filter {0}.").format(target_doctype),
					frappe.ValidationError,
				)
			if "province" in parsed_filters and parsed_filters["province"] != province:
				frappe.throw(_("province filters do not match."), frappe.ValidationError)
			parsed_filters["province"] = province
		options = _get_link_options(
			target_doctype, parsed_filters, search, parsed_limit, target_meta=target_meta
		)

	return {
		"doctype": doctype,
		"fieldname": fieldname,
		"fieldtype": field.fieldtype,
		"target_doctype": target_doctype,
		"options": options,
	}


@frappe.whitelist(methods=["POST", "PUT"])
def update_student(name: str, fields: dict | str | None = None) -> dict:
	"""Partially update basic profile fields on one CRM Lead.

	Request fields: ``name`` and a non-empty ``fields`` object. The response
	contains the document name and the normalized values that were updated.
	"""
	return _update_document("CRM Lead", name, fields, _STUDENT_BASIC_FIELDS)


@frappe.whitelist(methods=["POST", "PUT"])
def update_school(name: str, fields: dict | str | None = None) -> dict:
	"""Partially update basic profile fields on one CRM High School.

	School identity, lifecycle, and key-account governance fields are managed by
	separate business workflows and are intentionally excluded here.
	"""
	return _update_document("CRM High School", name, fields, _SCHOOL_BASIC_FIELDS)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_student(name: str) -> dict:
	"""Delete one CRM Student after checking delete permission and links."""
	return _delete_document("CRM Lead", name)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_school(name: str) -> dict:
	"""Delete one CRM High School after checking permission and dependencies."""
	return _delete_document("CRM High School", name)
