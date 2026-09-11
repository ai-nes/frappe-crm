"""APIs for Student and High School records and their form options."""

from __future__ import annotations

import json
import math

import frappe
from frappe import _

from crm.api.lead_mapping import _normalize_lead_payload
from crm.fcrm.doctype.crm_student.crm_student import MAX_GRADUATION_SCORE
from crm.fcrm.role_policy import resolve_crm_profile
from crm.fcrm.student_reference import canonical_student

_STUDENT_BASIC_FIELDS = frozenset(
	{
		"student_name",
		"full_name",
		"phone",
		"email",
		"other_email",
		"other_phone",
		"parent_other_phone",
		"parent_email",
		"father_name",
		"father_phone",
		"father_email",
		"father_occupation",
		"mother_name",
		"mother_phone",
		"mother_email",
		"mother_occupation",
		"gender",
		"date_of_birth",
		"birth_place",
		"ethnicity",
		"religion",
		"nationality",
		"province",
		"ward",
		"contact_address",
		"high_school",
		"current_grade",
		"study_stage",
		"branch",
		"major",
		"aspiration",
		"education_program",
		"admission_method",
		"platform",
		"admission_year",
		"alt_name",
		"alt_phone",
		"alt_address",
		"id_number",
		"id_issued_date",
		"id_issued_place",
		"decision_maker",
		"preferred_contact_channel",
		"notes",
	}
)
_STUDENT_PAYMENT_ACCOUNT_FIELDS = frozenset({"bank_name", "account_number", "account_holder"})
_STUDENT_WITH_LEAD_FIELDS = _STUDENT_BASIC_FIELDS | {
	"source",
	"assigned_to",
	"description",
	"campaign_code",
	"tags",
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
_OPTION_DOCTYPES = frozenset({"CRM Lead", "CRM Student", "CRM High School"})
_OPTION_FIELD_TYPES = frozenset({"Link", "Select"})
_DEFAULT_OPTION_LIMIT = 20
_MAX_OPTION_LIMIT = 100
_CTV_STUDENT_UPDATE_FIELDS = frozenset({"notes"})
_STUDENT_FIELD_ALIASES = {
	"student_name": "full_name",
	"alt_name": "parent_name",
	"alt_phone": "parent_phone",
	"alt_address": "contact_address",
}
_STUDENT_CANONICAL_FIELDS = frozenset(
	_STUDENT_FIELD_ALIASES.get(fieldname, fieldname) for fieldname in _STUDENT_BASIC_FIELDS
)
_PAYMENT_ACCOUNT_FIELD_ALIASES = {"account_holder": "account_holder_name"}
_STUDENT_HIGH_SCHOOL_SCORE_STUDENT_FIELDS = frozenset({"graduation_score", "transcript_score", "total_score"})
_STUDENT_HIGH_SCHOOL_SCORE_PROFILE_FIELDS = frozenset(
	{
		"is_high_school_graduate",
		"graduation_year",
		"priority_group",
		"graduation_classification",
		"conduct_rank",
		"grade_12_gpa",
		"exam_candidate_number",
		"score_details",
		"encouragement_type",
		"encouragement_score",
		"priority_type",
		"priority_score",
	}
)
_STUDENT_HIGH_SCHOOL_SCORE_ACADEMIC_FIELDS = frozenset({"academic_rank"})
_STUDENT_HIGH_SCHOOL_SCORE_FIELDS = (
	_STUDENT_HIGH_SCHOOL_SCORE_STUDENT_FIELDS
	| _STUDENT_HIGH_SCHOOL_SCORE_PROFILE_FIELDS
	| _STUDENT_HIGH_SCHOOL_SCORE_ACADEMIC_FIELDS
)
_STUDENT_HIGH_SCHOOL_SCORE_NUMERIC_FIELDS = frozenset(
	{
		"graduation_score",
		"transcript_score",
		"total_score",
		"grade_12_gpa",
		"encouragement_score",
		"priority_score",
	}
)
_STUDENT_HIGH_SCHOOL_SCORE_MAX_VALUES = {"graduation_score": MAX_GRADUATION_SCORE}
_STUDENT_HIGH_SCHOOL_SCORE_INTEGER_FIELDS = frozenset({"graduation_year"})
_STUDENT_HIGH_SCHOOL_SCORE_BOOLEAN_FIELDS = frozenset({"is_high_school_graduate"})
_STUDENT_HIGH_SCHOOL_SCORE_TEXT_FIELDS = frozenset(
	{
		"academic_rank",
		"conduct_rank",
		"exam_candidate_number",
		"encouragement_type",
		"graduation_classification",
		"priority_group",
		"priority_type",
	}
)


def _canonical_student_fields(fields: dict | str | None) -> dict:
	"""Translate the legacy form keys into the canonical Student schema."""
	values = _parse_fields(fields, _STUDENT_BASIC_FIELDS)
	canonical = {}
	for fieldname, value in values.items():
		canonical_name = _STUDENT_FIELD_ALIASES.get(fieldname, fieldname)
		if canonical_name in canonical and canonical[canonical_name] != value:
			frappe.throw(
				_("Only one value may be supplied for {0}.").format(canonical_name),
				frappe.ValidationError,
			)
		canonical[canonical_name] = value
	return canonical


def _student_response_fields(values: dict) -> dict:
	"""Expose compatibility aliases without making Lead the response source."""
	result = dict(values)
	for legacy_name, canonical_name in _STUDENT_FIELD_ALIASES.items():
		if canonical_name in result:
			result[legacy_name] = result[canonical_name]
	return result


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
	_check_student_update_permission(doctype, values)
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


def _check_student_update_permission(doctype: str, values: dict) -> None:
	if doctype != "CRM Student":
		return
	actor = getattr(getattr(frappe, "session", None), "user", None)
	profile = (
		resolve_crm_profile(frappe.get_roles(actor))
		if actor not in {None, "Guest", "None", "Administrator"}
		else None
	)
	if profile == "ctv_sale":
		unauthorized_fields = set(values) - _CTV_STUDENT_UPDATE_FIELDS
		if unauthorized_fields:
			frappe.throw(
				_("CTV Sale may only update: {0}.").format(", ".join(sorted(_CTV_STUDENT_UPDATE_FIELDS))),
				frappe.PermissionError,
			)


def _update_payment_account(name: str, fields: dict) -> dict:
	"""Update the primary contact payment account without duplicating it on CRM Student."""
	student = frappe.get_doc("CRM Student", name)
	student.check_permission("write")
	accounts = frappe.get_all(
		"CRM Student Payment Account",
		filters={"student": name},
		fields=["name"],
		order_by="is_primary desc, modified desc",
		limit_page_length=1,
	)
	if accounts:
		account = frappe.get_doc("CRM Student Payment Account", accounts[0]["name"])
		account.check_permission("write")
	else:
		account = frappe.new_doc("CRM Student Payment Account")
		account.student = name
		account.account_purpose = "Other"
		account.is_primary = 1
		account.check_permission("create")

	for fieldname, value in fields.items():
		account.set(_PAYMENT_ACCOUNT_FIELD_ALIASES.get(fieldname, fieldname), value)
	if accounts:
		account.save()
	else:
		_validate_required_fields(fields, frozenset(_PAYMENT_ACCOUNT_FIELD_ALIASES))
		account.insert()

	return {
		fieldname: account.get(_PAYMENT_ACCOUNT_FIELD_ALIASES.get(fieldname, fieldname))
		for fieldname in fields
	}


def _normalize_score_value(fieldname: str, value):
	if fieldname in _STUDENT_HIGH_SCHOOL_SCORE_INTEGER_FIELDS:
		if value in (None, ""):
			return None
		if isinstance(value, bool) or not isinstance(value, int):
			frappe.throw(_("{0} must be an integer.").format(fieldname), frappe.ValidationError)
		return value

	if fieldname in _STUDENT_HIGH_SCHOOL_SCORE_BOOLEAN_FIELDS:
		if value in (None, ""):
			return None
		if isinstance(value, bool):
			return value
		if value in (0, 1):
			return bool(value)
		frappe.throw(_("{0} must be a boolean.").format(fieldname), frappe.ValidationError)

	if fieldname in _STUDENT_HIGH_SCHOOL_SCORE_NUMERIC_FIELDS:
		if value in (None, ""):
			return None
		if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
			frappe.throw(
				_("{0} must be a finite non-negative number.").format(fieldname),
				frappe.ValidationError,
			)
		if value < 0:
			frappe.throw(_("{0} cannot be negative.").format(fieldname), frappe.ValidationError)
		maximum = _STUDENT_HIGH_SCHOOL_SCORE_MAX_VALUES.get(fieldname)
		if maximum is not None and value > maximum:
			frappe.throw(
				_("{0} must be between 0 and {1}.").format(fieldname, maximum),
				frappe.ValidationError,
			)
		return value

	if fieldname == "score_details":
		if value in (None, ""):
			return None
		if isinstance(value, str):
			try:
				value = json.loads(value)
			except (TypeError, ValueError):
				frappe.throw(_("score_details must be valid JSON."), frappe.ValidationError)
		if not isinstance(value, (dict, list)):
			frappe.throw(_("score_details must be a JSON object or array."), frappe.ValidationError)
		return value

	if fieldname in _STUDENT_HIGH_SCHOOL_SCORE_TEXT_FIELDS:
		if value in (None, ""):
			return None
		if not isinstance(value, str):
			frappe.throw(_("{0} must be a string.").format(fieldname), frappe.ValidationError)
		return value.strip() or None

	return value


def _read_score_details(value):
	if value in (None, ""):
		return None
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except (TypeError, ValueError):
			return None
	return value if isinstance(value, (dict, list)) else None


def _academic_rank(student) -> str | None:
	rows = student.get("academic_results") or []
	for row in reversed(rows):
		if row.get("grade") == "12":
			return row.get("academic_rank")
	return None


def _set_academic_rank(student, value: str | None, school_year: str | None) -> None:
	rows = student.get("academic_results") or []
	for row in reversed(rows):
		if row.get("grade") != "12":
			continue
		row.set("academic_rank", value) if hasattr(row, "set") else row.update(academic_rank=value)
		return

	if value is None:
		return
	if not school_year:
		frappe.throw(
			_("A school year is required to create the Grade 12 academic result."),
			frappe.ValidationError,
		)
	student.append(
		"academic_results",
		{"school_year": str(school_year), "grade": "12", "academic_rank": value},
	)


def _score_profile(student_name: str, admission_year: str | None = None, *, permission_type="read"):
	filters = {"student": student_name}
	if admission_year:
		filters["admission_year"] = admission_year
	rows = frappe.get_list(
		"CRM Student Admission Profile",
		filters=filters,
		fields=["name", "admission_year", "attempt_number", "modified"],
		order_by="modified desc, attempt_number desc, name desc",
		limit_page_length=1,
	)
	if not rows:
		return None

	profile = frappe.get_doc("CRM Student Admission Profile", rows[0]["name"])
	try:
		profile.check_permission(permission_type)
	except frappe.PermissionError:
		if permission_type == "read":
			return None
		raise
	return profile


def _student_high_school_score_payload(student, profile, admission_year: str | None = None) -> dict:
	profile_values = profile or {}
	resolved_year = profile_values.get("admission_year") or admission_year or student.get("admission_year")
	fields = {
		"graduation_score": student.get("graduation_score"),
		"transcript_score": student.get("transcript_score"),
		"total_score": student.get("total_score"),
		"is_high_school_graduate": (bool(profile_values.get("is_high_school_graduate")) if profile else None),
		"graduation_year": profile_values.get("graduation_year"),
		"academic_rank": _academic_rank(student),
		"priority_group": profile_values.get("priority_group"),
		"graduation_classification": profile_values.get("graduation_classification"),
		"conduct_rank": profile_values.get("conduct_rank"),
		"grade_12_gpa": profile_values.get("grade_12_gpa"),
		"exam_candidate_number": profile_values.get("exam_candidate_number"),
		"score_details": _read_score_details(profile_values.get("score_details")),
		"encouragement_type": profile_values.get("encouragement_type"),
		"encouragement_score": profile_values.get("encouragement_score"),
		"priority_type": profile_values.get("priority_type"),
		"priority_score": profile_values.get("priority_score"),
	}
	return {
		"doctype": "CRM Student",
		"name": student.name,
		"admission_profile": profile.name if profile else None,
		"admission_year": resolved_year,
		"fields": fields,
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


def _create_student_document(fields: dict | str | None) -> dict:
	result = _create_document(
		"CRM Student",
		_canonical_student_fields(fields),
		_STUDENT_CANONICAL_FIELDS,
		{"full_name"},
	)
	result["created_fields"] = _student_response_fields(result["created_fields"])
	return result


def _resolve_student_name(name: str) -> str:
	if not isinstance(name, str) or not name.strip():
		frappe.throw(_("Document name is required."), frappe.ValidationError)
	return canonical_student(name.strip()) or name.strip()


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
	field_aliases = {
		"student_name": "full_name",
		"alt_name": "parent_name",
		"alt_phone": "parent_phone",
		"alt_address": "contact_address",
	}
	if lead_code and "lead_code" in student_fields:
		student_values["lead_code"] = lead_code
	for fieldname, value in values.items():
		student_field = field_aliases.get(fieldname, fieldname)
		if student_field in student_fields and value not in (None, ""):
			student_values[student_field] = value
	return student_values


def _create_student_with_lead(fields: dict | str | None) -> dict:
	values = _parse_fields(fields, _STUDENT_WITH_LEAD_FIELDS)
	lead_values, tags, _events, assigned_user = _normalize_lead_payload(values)
	converted_at = frappe.utils.now_datetime()

	lead = frappe.get_doc({"doctype": "CRM Lead", **lead_values})
	lead.check_permission("create")

	savepoint = f"create_student_with_lead_{frappe.generate_hash(length=8)}"
	frappe.db.savepoint(savepoint)
	try:
		lead.insert()
		student_values = _student_values_from_lead(lead_values, lead.name, lead.get("lead_code"))
		student_values.update({"student_stage": "New", "converted_at": converted_at})
		if tags:
			student_values["tags"] = [{"tag": tag} for tag in tags]
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
		previous_flag = getattr(frappe.flags, "lead_processing_service", False)
		frappe.flags.lead_processing_service = True
		try:
			lead.save(ignore_permissions=True, ignore_version=False)
		finally:
			frappe.flags.lead_processing_service = previous_flag
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
			"campaign": student.get("campaign"),
			"source": student.get("source"),
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
				"campaign",
				"source",
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


def _get_school_area_options(high_school: str, search: str | None, limit: int) -> list[dict]:
	"""Return the area configured on one selected high school."""
	rows = frappe.get_list(
		"CRM High School",
		filters={"name": high_school},
		fields=["school_area"],
		limit_page_length=1,
	)
	if not rows or not rows[0].get("school_area"):
		return []
	return _get_link_options(
		"CRM School Area",
		{"code": rows[0].get("school_area")},
		search,
		limit,
	)


@frappe.whitelist(methods=["POST"])
def create_student(fields: dict | str | None = None) -> dict:
	"""Create the canonical CRM Student record.

	Lead intake remains available through ``create_student_with_lead``; this
	route must not create a second, Lead-shaped Student record.
	"""
	return _create_student_document(fields)


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
	result = _get_document("CRM Student", _resolve_student_name(name))
	result["fields"] = _student_response_fields(result["fields"])
	return result


@frappe.whitelist(methods=["GET"])
def get_student_high_school_score(name: str, admission_year: str | None = None) -> dict:
	"""Get the high-school score fields owned by Student and its admission profile."""
	student_name = _resolve_student_name(name)
	student = frappe.get_doc("CRM Student", student_name)
	student.check_permission("read")
	admission_year = _parse_text_filter(admission_year, "admission_year") or student.get("admission_year")
	profile = _score_profile(student.name, admission_year)
	return _student_high_school_score_payload(student, profile, admission_year)


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
	high_school: str | None = None,
) -> dict:
	"""Get options for any Link or Select field on Student or High School.

	``high_school`` is supported for ``CRM High School.school_area`` and makes
	the lookup return only the area configured on that selected school.
	"""
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
	high_school = _parse_text_filter(high_school, "high_school")
	if high_school and (doctype, fieldname) != ("CRM High School", "school_area"):
		frappe.throw(
			_("high_school can only be used to filter CRM High School.school_area."),
			frappe.ValidationError,
		)
	if high_school and province:
		frappe.throw(_("province and high_school cannot be used together."), frappe.ValidationError)

	if field.fieldtype == "Select":
		if province:
			frappe.throw(_("province can only be used with a Link field."), frappe.ValidationError)
		if high_school:
			frappe.throw(_("high_school can only be used with a Link field."), frappe.ValidationError)
		options = _get_select_options(field, search, parsed_limit)
		target_doctype = None
	else:
		target_doctype = (field.options or "").strip()
		if not target_doctype:
			frappe.throw(_("Link field {0} has no target doctype.").format(fieldname), frappe.ValidationError)
		target_meta = frappe.get_meta(target_doctype) if province else None
		if high_school:
			options = _get_school_area_options(high_school, search, parsed_limit)
		elif province:
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
		else:
			options = _get_link_options(target_doctype, parsed_filters, search, parsed_limit)

	return {
		"doctype": doctype,
		"fieldname": fieldname,
		"fieldtype": field.fieldtype,
		"target_doctype": target_doctype,
		"options": options,
	}


@frappe.whitelist(methods=["POST", "PUT"])
def update_student(name: str, fields: dict | str | None = None) -> dict:
	"""Partially update Student profile and associated contact account fields.

	Request fields: ``name`` and a non-empty ``fields`` object. The response
	contains the document name and the normalized values that were updated.
	"""
	values = _parse_fields(fields, _STUDENT_BASIC_FIELDS | _STUDENT_PAYMENT_ACCOUNT_FIELDS)
	_check_student_update_permission("CRM Student", values)
	student_name = _resolve_student_name(name)
	student_values = {
		fieldname: value for fieldname, value in values.items() if fieldname in _STUDENT_BASIC_FIELDS
	}
	payment_values = {
		fieldname: value
		for fieldname, value in values.items()
		if fieldname in _STUDENT_PAYMENT_ACCOUNT_FIELDS
	}
	result = {
		"doctype": "CRM Student",
		"name": student_name,
		"updated_fields": {},
	}
	if student_values:
		student_result = _update_document(
			"CRM Student",
			student_name,
			_canonical_student_fields(student_values),
			_STUDENT_CANONICAL_FIELDS,
		)
		result["updated_fields"].update(_student_response_fields(student_result["updated_fields"]))
	if payment_values:
		result["updated_fields"].update(_update_payment_account(student_name, payment_values))
	return result


@frappe.whitelist(methods=["POST", "PUT"])
def update_student_high_school_score(
	name: str,
	fields: dict | str | None = None,
	admission_year: str | None = None,
) -> dict:
	"""Update the score fields shown by the Student Detail high-school card."""
	values = _parse_fields(fields, _STUDENT_HIGH_SCHOOL_SCORE_FIELDS)
	values = {fieldname: _normalize_score_value(fieldname, value) for fieldname, value in values.items()}
	student_name = _resolve_student_name(name)
	student = frappe.get_doc("CRM Student", student_name)
	student.check_permission("write")
	admission_year = _parse_text_filter(admission_year, "admission_year") or student.get("admission_year")
	student_values = {
		fieldname: value
		for fieldname, value in values.items()
		if fieldname in _STUDENT_HIGH_SCHOOL_SCORE_STUDENT_FIELDS
	}
	profile_values = {
		fieldname: value
		for fieldname, value in values.items()
		if fieldname in _STUDENT_HIGH_SCHOOL_SCORE_PROFILE_FIELDS
	}
	academic_values = {
		fieldname: value
		for fieldname, value in values.items()
		if fieldname in _STUDENT_HIGH_SCHOOL_SCORE_ACADEMIC_FIELDS
	}
	profile = (
		_score_profile(student.name, admission_year, permission_type="write") if profile_values else None
	)
	if profile_values and not profile:
		frappe.throw(
			_("No admission profile exists for this Student and admission year."),
			frappe.DoesNotExistError,
		)

	for fieldname, value in student_values.items():
		student.set(fieldname, value)
	if academic_values:
		academic_year = (
			profile_values.get("graduation_year")
			or (profile.get("graduation_year") if profile else None)
			or admission_year
			or student.get("admission_year")
		)
		_set_academic_rank(student, academic_values["academic_rank"], academic_year)
	if student_values or academic_values:
		student.save()

	for fieldname, value in profile_values.items():
		profile.set(
			fieldname,
			frappe.as_json(value) if fieldname == "score_details" and value is not None else value,
		)
	if profile_values:
		profile.save()

	result = _student_high_school_score_payload(student, profile, admission_year)
	result["updated_fields"] = values
	return result


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
	return _delete_document("CRM Student", _resolve_student_name(name))


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_school(name: str) -> dict:
	"""Delete one CRM High School after checking permission and dependencies."""
	return _delete_document("CRM High School", name)
