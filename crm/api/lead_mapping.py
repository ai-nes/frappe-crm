"""Lead mapping contract for the CSV intake used by ``dashboard-crm``.

The canonical admissions record remains ``CRM Lead``.  This module is a
small compatibility boundary: it accepts the CSV vocabulary, resolves lookup
labels to CRM records, enforces the CSV nullability/uniqueness rules, and then
delegates event evidence to the audited attribution service.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from collections.abc import Iterable
from typing import Any

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from crm.api.routing import route_new_lead
from crm.fcrm.student_attribution import record_event_participation
from crm.fcrm.utils.geo_resolver import (
	resolve_high_school_strict,
	resolve_province,
	resolve_ward,
)

MAX_IMPORT_ROWS = 1000
_PHONE_PATTERN = re.compile(r"0\d{9}")
_CONVERSION_POTENTIALS = ("High", "Medium", "Low", "Unknown")


class LeadMappingError(frappe.ValidationError):
	"""Stable validation error that can be returned per CSV row."""

	def __init__(self, code: str, message: str):
		self.code = code
		super().__init__(f"{code}: {message}")


def _fail(code: str, message: str):
	raise LeadMappingError(code, message)


def _require_authenticated() -> None:
	actor = _text(getattr(frappe.session, "user", None))
	if not actor or actor in {"Guest", "None"}:
		_fail("UNAUTHORIZED", "Đăng nhập là bắt buộc.")


def _text(value: Any) -> str | None:
	if value is None:
		return None
	value = str(value).strip()
	return value or None


def _normalize_header(value: Any) -> str:
	text = str(value or "").replace("đ", "d").replace("Đ", "D")
	text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
	text = text.casefold().replace("_", " ")
	return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _normalize_catalog_label(value: Any) -> str:
	text = _normalize_header(value)
	text = re.sub(r"^(tp|thanh pho|tinh)\s+", "", text)
	return re.sub(r"\s+(city|province|tinh|thanh pho)$", "", text).strip()


_HEADER_ALIASES = {
	"ho va ten": "student_name",
	"full name": "student_name",
	"student name": "student_name",
	"di dong": "phone",
	"mobile": "phone",
	"phone": "phone",
	"email": "email",
	"email khac": "other_email",
	"other email": "other_email",
	"tinh thanh pho": "province",
	"province city": "province",
	"province": "province",
	"truong thpt": "high_school",
	"high school": "high_school",
	"nganh quan tam": "major",
	"interested major": "major",
	"major": "major",
	"kenh quang cao": "advertising_channel",
	"ad channel": "advertising_channel",
	"advertising channel": "advertising_channel",
	"segments": "segments",
	"nam tuyen sinh": "admission_year",
	"enrollment year": "admission_year",
	"admission year": "admission_year",
	"kha nang chuyen doi": "conversion_potential",
	"conversion potential": "conversion_potential",
	"nguon": "source",
	"source": "source",
	"tinh trang lead": "enrollment_status",
	"lead status": "enrollment_status",
	"enrollment status": "enrollment_status",
	"giao cho": "assigned_to",
	"assigned to": "assigned_to",
	"chi nhanh": "branch",
	"branch": "branch",
	"tags": "tags",
	"nguyen vong vao fpt": "aspiration",
	"fpt aspiration": "aspiration",
	"su kien tham gia": "event_participated",
	"event participated": "event_participated",
	"mo ta": "description",
	"description": "description",
	"ghi chu": "notes",
	"notes": "notes",
}

_LEAD_FIELDS = frozenset(
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
		"major",
		"current_grade",
		"study_stage",
		"advertising_channel",
		"segments",
		"admission_year",
		"conversion_potential",
		"source",
		"enrollment_status",
		"assigned_to",
		"branch",
		"tags",
		"aspiration",
		"event_participated",
		"description",
		"notes",
		"alt_name",
		"alt_phone",
		"alt_address",
	}
)
_CSV_REQUIRED_HEADERS = frozenset({"student_name", "phone", "province", "source", "assigned_to"})

_PUBLIC_LEAD_FIELDS = frozenset(
	{
		"student_name",
		"phone",
		"email",
		"other_email",
		"gender",
		"date_of_birth",
		"source",
		"advertising_channel",
		"import_source_id",
		"segments",
		"assignment_priority",
		"branch",
		"id_number",
		"id_issued_date",
		"id_issued_place",
		"high_school",
		"current_grade",
		"study_stage",
		"province",
		"ward",
		"major",
		"aspiration",
		"admission_year",
		"step",
		"conversion_potential",
		"alt_name",
		"alt_phone",
		"alt_address",
		"notes",
	}
)
_PUBLIC_SERVER_MANAGED_FIELDS = frozenset(
	{
		"lead_code",
		"lead_status",
		"enrollment_status",
		"conversion_status",
		"conversion_blockers",
		"converted_student",
		"converted_at",
		"assigned_to",
		"owner_staff",
		"owning_team",
		"owning_pool",
		"privacy_status",
		"status_change_reason",
		"status_change_log",
		"assignment_log",
		"intake_integrity_state",
		"intake_quarantine_reason",
		"identity",
		"case_key",
		"student",
	}
)


def _parse_payload(payload: dict[str, Any] | str | None) -> dict[str, Any]:
	if isinstance(payload, str):
		try:
			payload = frappe.parse_json(payload)
		except (TypeError, ValueError):
			_fail("INVALID_INPUT", "fields phải là JSON object hợp lệ.")
	if not isinstance(payload, dict) or not payload:
		_fail("INVALID_INPUT", "fields phải là object không rỗng.")
	unknown = sorted(set(payload) - _LEAD_FIELDS)
	if unknown:
		_fail("UNKNOWN_FIELD", f"Field không được hỗ trợ: {', '.join(unknown)}.")
	return payload


def _parse_public_payload(payload: dict[str, Any] | str | None) -> dict[str, Any]:
	if isinstance(payload, str):
		try:
			payload = frappe.parse_json(payload)
		except (TypeError, ValueError):
			_fail("INVALID_INPUT", "fields phải là JSON object hợp lệ.")
	if not isinstance(payload, dict) or not payload:
		_fail("INVALID_INPUT", "fields phải là object không rỗng.")

	server_managed = sorted(set(payload) & _PUBLIC_SERVER_MANAGED_FIELDS)
	if server_managed:
		_fail(
			"SERVER_MANAGED_FIELD",
			f"Không được ghi các field server-managed: {', '.join(server_managed)}.",
		)
	unknown = sorted(set(payload) - _PUBLIC_LEAD_FIELDS - _PUBLIC_SERVER_MANAGED_FIELDS)
	if unknown:
		_fail("UNKNOWN_FIELD", f"Field không được hỗ trợ: {', '.join(unknown)}.")
	return payload


def split_multi_value(value: Any) -> list[str]:
	"""Parse the semicolon-separated MultiChoice representation from CSV."""
	if value is None:
		return []
	values: list[str] = []
	items: Iterable[Any] = value if isinstance(value, (list, tuple, set)) else [value]
	for item in items:
		if item is None:
			continue
		for part in re.split(r"[;\n]", str(item)):
			part = part.strip()
			if part and part not in values:
				values.append(part)
	return values


def _normalize_phone(value: Any) -> str:
	phone = _text(value)
	if phone and phone.startswith("+84"):
		phone = "0" + phone[3:]
	if not phone or not _PHONE_PATTERN.fullmatch(phone):
		_fail("INVALID_PHONE", "Di động phải gồm đúng 10 số và bắt đầu bằng 0.")
	return phone


def _resolve_link(doctype: str, value: Any, display_fields: tuple[str, ...], label: str) -> str:
	value = _text(value)
	if not value:
		_fail("INVALID_LOOKUP", f"{label} không hợp lệ.")
	if frappe.db.exists(doctype, value):
		return value
	for fieldname in display_fields:
		if not frappe.get_meta(doctype).has_field(fieldname):
			continue
		matches = frappe.get_all(
			doctype,
			filters={fieldname: value},
			pluck="name",
			limit_page_length=2,
		)
		if len(matches) == 1:
			return matches[0]
	_fail("INVALID_LOOKUP", f"Không tìm thấy {label}: {value}.")


def _resolve_province(value: Any) -> str:
	province_value = _text(value)
	if not province_value:
		_fail("REQUIRED_FIELD", "Tỉnh/Thành phố là bắt buộc.")
	province = resolve_province(province_value)
	if frappe.db.exists("CRM Province", province):
		return province
	target = _normalize_catalog_label(province_value)
	matches = [
		row.name
		for row in frappe.get_all("CRM Province", fields=["name", "province_name"], limit_page_length=0)
		if _normalize_catalog_label(row.province_name) == target
	]
	if len(matches) == 1:
		return matches[0]
	if len(matches) > 1:
		_fail("INVALID_PROVINCE", f"Tỉnh/Thành phố không xác định: {province_value}.")
	return province


def _resolve_source(value: Any) -> str:
	source = _resolve_link("CRM Lead Source", value, ("source_name",), "Nguồn")
	if frappe.db.get_value("CRM Lead Source", source, "approval_state") == "Retired":
		_fail("INVALID_SOURCE", "Nguồn đã retired và không thể dùng cho Lead mới.")
	return source


def _resolve_status(value: Any) -> str:
	status = _resolve_link("CRM Enrollment Status", value, ("code", "display_name"), "Tình trạng Lead")
	if frappe.db.get_value("CRM Enrollment Status", status, "enabled") == 0:
		_fail("INVALID_STATUS", "Tình trạng Lead đã bị tắt.")
	return status


def _resolve_assignment(value: Any) -> tuple[str, str, str | None]:
	requested = _text(value)
	actor = _text(getattr(frappe.session, "user", None))
	staff = None
	if requested:
		staff = frappe.db.get_value(
			"CRM Staff", requested, ["name", "user", "is_active", "campus"], as_dict=True
		)
		if not staff:
			staff = frappe.db.get_value(
				"CRM Staff", {"user": requested}, ["name", "user", "is_active", "campus"], as_dict=True
			)
	if not staff or not staff.get("name"):
		_fail("ASSIGNED_TO_REQUIRED", "Không xác định được CRM Staff cho field Giao cho.")
	if staff.get("is_active") == 0:
		_fail("ASSIGNED_TO_INACTIVE", "CRM Staff được giao Lead đang không hoạt động.")
	assigned_user = _text(staff.get("user"))
	if not assigned_user:
		_fail("ASSIGNED_TO_REQUIRED", "CRM Staff được giao Lead phải liên kết với User.")
	roles = set(frappe.get_roles(actor)) if actor else set()
	can_assign_any = actor == "Administrator" or bool(
		roles & {"System Manager", "Admissions Director", "Lead Sale"}
	)
	if not can_assign_any and assigned_user != actor:
		_fail("ASSIGNED_TO_FORBIDDEN", "Bạn chỉ được giao Lead cho chính mình.")
	return staff.name, assigned_user, staff.get("campus")


def _check_unique(fieldname: str, value: str, label: str):
	if frappe.db.exists("CRM Lead", {fieldname: value}):
		_fail(f"DUPLICATE_{fieldname.upper()}", f"{label} đã tồn tại trên một Lead/Student khác.")


def _normalize_lead_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str], str]:
	name = _text(payload.get("student_name"))
	if not name:
		_fail("REQUIRED_FIELD", "Họ và tên là bắt buộc.")
	phone = _normalize_phone(payload.get("phone"))
	_check_unique("phone", phone, "Di động")

	email = _text(payload.get("email"))
	if email:
		email = email.casefold()
		_check_unique("email", email, "Email")
	other_email = _text(payload.get("other_email"))
	if other_email:
		other_email = other_email.casefold()
	province_value = _text(payload.get("province"))
	if not province_value:
		_fail("REQUIRED_FIELD", "Tỉnh/Thành phố là bắt buộc.")
	province = _resolve_province(province_value)
	if not frappe.db.exists("CRM Province", province):
		_fail("INVALID_PROVINCE", f"Không tìm thấy Tỉnh/Thành phố: {province_value}.")

	assigned_to, assigned_user, staff_campus = _resolve_assignment(payload.get("assigned_to"))
	branch_value = _text(payload.get("branch")) or staff_campus
	branch = (
		_resolve_link("CRM Campus", branch_value, ("campus_name", "campus_code"), "Chi nhánh")
		if branch_value
		else None
	)

	source_value = _text(payload.get("source"))
	if not source_value:
		_fail("REQUIRED_FIELD", "Nguồn là bắt buộc.")
	source = _resolve_source(source_value)
	status = _resolve_status(payload.get("enrollment_status") or "NEW")

	high_school_value = _text(payload.get("high_school"))
	high_school = resolve_high_school_strict(high_school_value, province) if high_school_value else None
	ward_value = _text(payload.get("ward"))
	ward = resolve_ward(ward_value, province) if ward_value else None
	if ward and not frappe.db.exists("CRM Ward", ward):
		_fail("INVALID_WARD", f"Không tìm thấy Phường/Xã: {ward_value}.")
	if high_school and not frappe.db.exists("CRM High School", high_school):
		_fail("INVALID_HIGH_SCHOOL", f"Không tìm thấy Trường THPT: {high_school_value}.")

	major_value = _text(payload.get("major"))
	major = (
		_resolve_link("CRM Major", major_value, ("major_name", "major_code"), "Ngành quan tâm")
		if major_value
		else None
	)
	aspiration_value = _text(payload.get("aspiration"))
	aspiration = (
		_resolve_link("CRM Aspiration", aspiration_value, ("code", "display_name"), "Nguyện vọng")
		if aspiration_value
		else None
	)
	admission_year_value = _text(payload.get("admission_year"))
	admission_year = (
		_resolve_link("CRM Admission Year", admission_year_value, ("year_name",), "Năm tuyển sinh")
		if admission_year_value
		else None
	)

	conversion_value = _text(payload.get("conversion_potential"))
	conversion_potential = (
		next(
			(option for option in _CONVERSION_POTENTIALS if option.casefold() == conversion_value.casefold()),
			None,
		)
		if conversion_value
		else None
	)
	if conversion_value and not conversion_potential:
		_fail("INVALID_OPTION", f"Khả năng chuyển đổi không hợp lệ: {conversion_value}.")

	advertising_channel = _text(payload.get("advertising_channel"))
	if advertising_channel:
		advertising_channel = _resolve_source(advertising_channel)

	segments = split_multi_value(payload.get("segments"))
	tags = split_multi_value(payload.get("tags"))
	events = split_multi_value(payload.get("event_participated"))
	description = _text(payload.get("description"))
	if not description:
		description = _text(payload.get("notes"))

	values = {
		"student_name": name,
		"phone": phone,
		"email": email,
		"other_email": other_email,
		"gender": _text(payload.get("gender")),
		"date_of_birth": _text(payload.get("date_of_birth")),
		"province": province,
		"ward": ward,
		"high_school": high_school,
		"major": major,
		"current_grade": _text(payload.get("current_grade")),
		"study_stage": _text(payload.get("study_stage")),
		"advertising_channel": advertising_channel,
		"segments": frappe.as_json(segments) if segments else None,
		"admission_year": admission_year,
		"conversion_potential": conversion_potential,
		"source": source,
		"enrollment_status": status,
		"assigned_to": assigned_to,
		"branch": branch,
		"aspiration": aspiration,
		"alt_name": _text(payload.get("alt_name")),
		"alt_phone": _text(payload.get("alt_phone")),
		"alt_address": _text(payload.get("alt_address")),
		"notes": description,
	}
	return values, tags, events, assigned_user


def _normalize_public_segments(value: Any) -> str | None:
	if value in (None, ""):
		return None
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			_fail("INVALID_SEGMENTS", "segments phải là JSON array.")
	if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
		_fail("INVALID_SEGMENTS", "segments phải là JSON array gồm các chuỗi không rỗng.")
	return frappe.as_json(list(dict.fromkeys(item.strip() for item in value)))


def _normalize_public_lead_payload(payload: dict[str, Any]) -> dict[str, Any]:
	name = _text(payload.get("student_name"))
	if not name:
		_fail("REQUIRED_FIELD", "Họ và tên là bắt buộc.")

	phone_value = _text(payload.get("phone"))
	phone = _normalize_phone(phone_value) if phone_value else None
	if phone:
		_check_unique("phone", phone, "Di động")

	email = _text(payload.get("email"))
	if email:
		email = email.casefold()
		_check_unique("email", email, "Email")
	other_email = _text(payload.get("other_email"))
	if other_email:
		other_email = other_email.casefold()

	province_value = _text(payload.get("province"))
	province = _resolve_province(province_value) if province_value else None
	if province and not frappe.db.exists("CRM Province", province):
		_fail("INVALID_PROVINCE", f"Không tìm thấy Tỉnh/Thành phố: {province_value}.")

	ward_value = _text(payload.get("ward"))
	ward = resolve_ward(ward_value, province) if ward_value else None
	if ward and not frappe.db.exists("CRM Ward", ward):
		_fail("INVALID_WARD", f"Không tìm thấy Phường/Xã: {ward_value}.")

	high_school_value = _text(payload.get("high_school"))
	high_school = resolve_high_school_strict(high_school_value, province) if high_school_value else None
	if high_school and not frappe.db.exists("CRM High School", high_school):
		_fail("INVALID_HIGH_SCHOOL", f"Không tìm thấy Trường THPT: {high_school_value}.")

	branch_value = _text(payload.get("branch"))
	branch = (
		_resolve_link("CRM Campus", branch_value, ("campus_name", "campus_code"), "Chi nhánh")
		if branch_value
		else frappe.db.get_value("CRM Campus", {"is_default": 1}, "name")
	)

	source_value = _text(payload.get("source"))
	source = _resolve_source(source_value) if source_value else None
	major_value = _text(payload.get("major"))
	major = (
		_resolve_link("CRM Major", major_value, ("major_name", "major_code"), "Ngành quan tâm")
		if major_value
		else None
	)
	aspiration_value = _text(payload.get("aspiration"))
	aspiration = (
		_resolve_link("CRM Aspiration", aspiration_value, ("code", "display_name"), "Nguyện vọng")
		if aspiration_value
		else None
	)
	admission_year_value = _text(payload.get("admission_year"))
	admission_year = (
		_resolve_link("CRM Admission Year", admission_year_value, ("year_name",), "Năm tuyển sinh")
		if admission_year_value
		else None
	)

	conversion_value = _text(payload.get("conversion_potential"))
	conversion_potential = (
		next(
			(option for option in _CONVERSION_POTENTIALS if option.casefold() == conversion_value.casefold()),
			None,
		)
		if conversion_value
		else None
	)
	if conversion_value and not conversion_potential:
		_fail("INVALID_OPTION", f"Khả năng chuyển đổi không hợp lệ: {conversion_value}.")

	priority_value = _text(payload.get("assignment_priority"))
	assignment_priority = priority_value.casefold() if priority_value else None
	if assignment_priority and assignment_priority not in {"low", "normal", "high", "urgent"}:
		_fail("INVALID_OPTION", f"Độ ưu tiên không hợp lệ: {priority_value}.")

	step = payload.get("step")
	if step not in (None, ""):
		try:
			step = int(step)
		except (TypeError, ValueError):
			_fail("INVALID_STEP", "step phải là số nguyên không âm.")
		if step < 0:
			_fail("INVALID_STEP", "step phải là số nguyên không âm.")

	alt_phone_value = _text(payload.get("alt_phone"))
	alt_phone = _normalize_phone(alt_phone_value) if alt_phone_value else None

	return {
		"student_name": name,
		"phone": phone,
		"email": email,
		"other_email": other_email,
		"gender": _text(payload.get("gender")),
		"date_of_birth": _text(payload.get("date_of_birth")),
		"source": source,
		"advertising_channel": _text(payload.get("advertising_channel")),
		"import_source_id": _text(payload.get("import_source_id")),
		"segments": _normalize_public_segments(payload.get("segments")),
		"assignment_priority": assignment_priority,
		"branch": branch,
		"id_number": _text(payload.get("id_number")),
		"id_issued_date": _text(payload.get("id_issued_date")),
		"id_issued_place": _text(payload.get("id_issued_place")),
		"high_school": high_school,
		"current_grade": _text(payload.get("current_grade")),
		"study_stage": _text(payload.get("study_stage")),
		"province": province,
		"ward": ward,
		"major": major,
		"aspiration": aspiration,
		"admission_year": admission_year,
		"step": step,
		"conversion_potential": conversion_potential,
		"alt_name": _text(payload.get("alt_name")),
		"alt_phone": alt_phone,
		"alt_address": _text(payload.get("alt_address")),
		"notes": _text(payload.get("notes")),
	}


def _apply_tags(doc, tags: list[str]):
	for tag in tags:
		doc.add_tag(tag)


def _record_events(student: str, events: list[str]) -> list[dict[str, Any]]:
	if not events:
		return []
	actor = getattr(frappe.session, "user", None)
	previous_service = getattr(frappe.flags, "student_admissions_service", None)
	previous_scope = getattr(frappe.flags, "student_admissions_scope", None)
	frappe.flags.student_admissions_service = True
	frappe.flags.student_admissions_scope = {"actor": actor, "student": student}
	try:
		result = []
		for event in events:
			resolved_event = _resolve_link("CRM Event", event, ("title",), "Sự kiện")
			evidence = record_event_participation(
				student=student,
				crm_event=resolved_event,
				idempotency_key=f"lead-event:{student}:{resolved_event}",
				correlation_id=f"lead:{student}",
			)
			result.append({"event": resolved_event, "evidence": evidence})
		return result
	finally:
		frappe.flags.student_admissions_service = previous_service
		frappe.flags.student_admissions_scope = previous_scope


def _create_lead(fields: dict[str, Any]) -> dict[str, Any]:
	values, tags, events, assigned_user = _normalize_lead_payload(fields)
	doc = frappe.get_doc({"doctype": "CRM Lead", **values})
	doc.check_permission("create")
	doc.insert()
	_apply_tags(doc, tags)
	event_result = _record_events(doc.name, events)
	if not doc.get("assigned_to") or not doc.get("phone") or not doc.get("province") or not doc.get("source"):
		_fail("CONTRACT_VIOLATION", "Lead sau khi tạo chưa đáp ứng các field Required của CSV.")
	return {
		"doctype": "CRM Lead",
		"name": doc.name,
		"lead_code": doc.get("lead_code"),
		"leadCode": doc.get("lead_code"),
		"created_fields": {
			fieldname: doc.get(fieldname)
			for fieldname in (
				"lead_code",
				"lead_status",
				"conversion_status",
				"conversion_blockers",
				"student_name",
				"phone",
				"email",
				"other_email",
				"province",
				"high_school",
				"major",
				"advertising_channel",
				"segments",
				"admission_year",
				"conversion_potential",
				"source",
				"enrollment_status",
				"assigned_to",
				"branch",
				"aspiration",
				"notes",
			)
		},
		"assigned_to_user": assigned_user,
		"tags": tags,
		"event_participated": event_result,
	}


@frappe.whitelist(methods=["POST"])
def create_lead(fields: dict[str, Any] | str | None = None) -> dict[str, Any]:
	"""Create one CSV-compatible Lead backed by ``CRM Lead``."""
	_require_authenticated()
	return _create_lead(_parse_payload(fields))


def _create_public_lead(fields: dict[str, Any]) -> dict[str, Any]:
	values = _normalize_public_lead_payload(fields)
	doc = frappe.get_doc({"doctype": "CRM Lead", **values})
	route_new_lead(doc)
	doc.insert(ignore_permissions=True)
	return {
		"doctype": "CRM Lead",
		"name": doc.name,
		"lead_code": doc.get("lead_code"),
		"leadCode": doc.get("lead_code"),
		"lead_status": doc.get("lead_status"),
		"conversion_status": doc.get("conversion_status"),
		"conversion_blockers": doc.get("conversion_blockers"),
		"assigned_to": doc.get("assigned_to"),
		"branch": doc.get("branch"),
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=30, seconds=60)
def create_public_lead(
	fields: dict[str, Any] | str | None = None,
	**payload: Any,
) -> dict[str, Any]:
	"""Create one intake Lead without requiring an authenticated session.

	The public boundary accepts either ``{"fields": {...}}`` or the field
	dictionary directly as POST parameters. Ownership, status, consent and
	audit fields remain server-managed.
	"""
	if fields is not None and payload:
		_fail("INVALID_INPUT", "Gửi fields hoặc các field trực tiếp, không gửi cả hai.")
	return _create_public_lead(_parse_public_payload(fields if fields is not None else payload))


def _parse_csv_rows(csv_content: str) -> list[dict[str, Any]]:
	if not isinstance(csv_content, str) or not csv_content.strip():
		_fail("INVALID_CSV", "csv_content không được rỗng.")
	reader = csv.DictReader(io.StringIO(csv_content.lstrip("\ufeff")))
	if not reader.fieldnames:
		_fail("INVALID_CSV", "CSV không có header.")
	canonical_headers = {}
	for header in reader.fieldnames:
		canonical = _HEADER_ALIASES.get(_normalize_header(header))
		if canonical:
			canonical_headers[header] = canonical
	missing = sorted(_CSV_REQUIRED_HEADERS - set(canonical_headers.values()))
	if missing:
		_fail("CSV_MISSING_HEADERS", f"CSV thiếu cột bắt buộc: {', '.join(missing)}.")
	rows = []
	for row in reader:
		mapped = {
			canonical_headers[header]: value for header, value in row.items() if header in canonical_headers
		}
		if any(_text(value) for value in mapped.values()):
			rows.append(mapped)
	if not rows:
		_fail("INVALID_CSV", "CSV không có dòng dữ liệu.")
	if len(rows) > MAX_IMPORT_ROWS:
		_fail("CSV_TOO_LARGE", f"CSV tối đa {MAX_IMPORT_ROWS} dòng.")
	return rows


def _parse_import_rows(
	rows: list[dict[str, Any]] | str | None, csv_content: str | None
) -> list[dict[str, Any]]:
	if csv_content is not None:
		return _parse_csv_rows(csv_content)
	if isinstance(rows, str):
		try:
			rows = frappe.parse_json(rows)
		except (TypeError, ValueError):
			_fail("INVALID_ROWS", "rows phải là JSON array hợp lệ.")
	if not isinstance(rows, list) or not rows:
		_fail("INVALID_ROWS", "Cần truyền rows hoặc csv_content.")
	if len(rows) > MAX_IMPORT_ROWS:
		_fail("CSV_TOO_LARGE", f"CSV tối đa {MAX_IMPORT_ROWS} dòng.")
	return [_parse_payload(row) for row in rows]


def _row_error(error: Exception) -> dict[str, str]:
	if isinstance(error, LeadMappingError):
		return {"code": error.code, "message": str(error)}
	return {"code": "IMPORT_ROW_FAILED", "message": str(error)}


@frappe.whitelist(methods=["POST"])
def import_leads(
	rows: list[dict[str, Any]] | str | None = None,
	csv_content: str | None = None,
	filename: str | None = None,
) -> dict[str, Any]:
	"""Import CSV-compatible Leads with savepoint isolation per row."""
	_require_authenticated()
	parsed_rows = _parse_import_rows(rows, csv_content)
	created = []
	errors = []
	for index, row in enumerate(parsed_rows, start=2):
		savepoint = f"lead_mapping_row_{index}"
		frappe.db.savepoint(savepoint)
		try:
			created.append({"row": index, **_create_lead(row)})
		except Exception as error:
			frappe.db.rollback(save_point=savepoint)
			errors.append({"row": index, **_row_error(error)})
	return {
		"filename": _text(filename),
		"total": len(parsed_rows),
		"created": len(created),
		"failed": len(errors),
		"students": created,
		"errors": errors,
	}


def _option_rows(
	doctype: str,
	fields: list[str],
	limit: int = 100,
	value_field: str = "name",
	filters: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
	rows = frappe.get_list(
		doctype,
		fields=fields,
		filters=filters or {},
		limit_page_length=limit,
		order_by="modified desc",
	)
	return [
		{
			"value": row.get(value_field) or row.get("name") or row.get(fields[0]),
			"label": row.get("title") or row.get("display_name") or row.get("full_name") or row.get("name"),
			**({"user": row.get("user")} if "user" in fields else {}),
		}
		for row in rows
	]


@frappe.whitelist(methods=["GET"])
def get_lead_options(limit: int | str | None = None) -> dict[str, Any]:
	"""Return lookup options that are not represented by Student Link fields."""
	_require_authenticated()
	try:
		limit = min(max(int(limit or 100), 1), 100)
	except (TypeError, ValueError):
		_fail("INVALID_LIMIT", "limit phải là số nguyên.")
	ad_options = _option_rows(
		"CRM Lead Source",
		["name", "source_name"],
		limit,
		filters={"approval_state": ["!=", "Retired"]},
	)
	return {
		"staff": _option_rows(
			"CRM Staff",
			["name", "full_name", "user"],
			limit,
			"user",
			{"is_active": 1},
		),
		"segments": _option_rows("CRM Segment", ["name", "title"], limit),
		"events": _option_rows("CRM Event", ["name", "title"], limit),
		"advertising_channel": ad_options,
	}
