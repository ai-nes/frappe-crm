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
import math
import re
import unicodedata
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from crm.api.routing import route_new_lead
from crm.fcrm.campaign_code import is_valid_campaign_code
from crm.fcrm.campaign_source import resolve_campaign_reference as resolve_campaign_name
from crm.fcrm.student_attribution import record_event_participation
from crm.fcrm.student_intake import normalize_national_id
from crm.fcrm.utils.geo_resolver import (
	resolve_high_school_strict,
	resolve_province,
	resolve_ward,
)

MAX_IMPORT_ROWS = 1000
MAX_IMPORT_FILE_BYTES = 5 * 1024 * 1024
_PHONE_PATTERN = re.compile(r"0\d{9}")
_CONVERSION_POTENTIALS = ("High", "Medium", "Low", "Unknown")
_IMPORT_MODES = frozenset({"legacy", "quick_create"})
_QUICK_IMPORT_CAMPAIGN_STATUSES = frozenset({"ACTIVE", "CLOSED"})
PUBLIC_LEAD_LIST_FIELDS = (
	"name",
	"lead_code",
	"student_name",
	"phone",
	"email",
	"major",
	"high_school",
	"province",
	"ward",
	"processing_status",
	"resolution",
	"campaign",
	"creation",
)
MAX_PUBLIC_LEAD_PAGE_LENGTH = 100
_PUBLIC_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PUBLIC_LEAD_LINK_LABELS = {
	"province": ("CRM Province", "province_name"),
	"ward": ("CRM Ward", "ward_name"),
	"high_school": ("CRM High School", "school_name"),
}


class LeadMappingError(frappe.ValidationError):
	"""Stable validation error that can be returned per CSV row."""

	def __init__(self, code: str, message: str):
		super().__init__(f"{code}: {message}")
		self.code = code
		self.message = message


def _fail(code: str, message: str):
	raise LeadMappingError(code, message)


def _require_authenticated() -> None:
	actor = _text(getattr(frappe.session, "user", None))
	if not actor or actor in {"Guest", "None"}:
		_fail("UNAUTHORIZED", "Đăng nhập là bắt buộc.")


def _require_lead_create_permission() -> None:
	if not frappe.has_permission("CRM Lead", "create"):
		_fail("FORBIDDEN", "Bạn không có quyền tạo Lead.")


def _text(value: Any) -> str | None:
	if value is None:
		return None
	value = str(value).strip()
	return value or None


def _parse_public_int(
	value: Any, fieldname: str, *, default: int, minimum: int, maximum: int | None = None
) -> int:
	if value in (None, ""):
		return default
	try:
		parsed = int(value)
	except (TypeError, ValueError):
		_fail("INVALID_PAGINATION", f"{fieldname} phải là số nguyên.")
	if parsed < minimum or (maximum is not None and parsed > maximum):
		bounds = f"{minimum} và {maximum}" if maximum is not None else f"ít nhất {minimum}"
		_fail("INVALID_PAGINATION", f"{fieldname} phải nằm trong khoảng {bounds}.")
	return parsed


def _parse_public_date(value: Any, fieldname: str) -> date | None:
	value = _text(value)
	if not value:
		return None
	if not _PUBLIC_DATE_PATTERN.fullmatch(value):
		_fail("INVALID_DATE", f"{fieldname} phải có định dạng YYYY-MM-DD.")
	try:
		return date.fromisoformat(value)
	except ValueError:
		_fail("INVALID_DATE", f"{fieldname} không phải là ngày hợp lệ.")


def _coalesce_public_date(primary: Any, alias: Any, fieldname: str) -> str | None:
	primary = _text(primary)
	alias = _text(alias)
	if primary and alias and primary != alias:
		_fail("INVALID_DATE", f"Chỉ được gửi một giá trị cho {fieldname}.")
	return primary or alias


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
	"so dien thoai": "phone",
	"mobile": "phone",
	"phone": "phone",
	"email": "email",
	"email khac": "other_email",
	"other email": "other_email",
	"tinh thanh pho": "province",
	"province city": "province",
	"province": "province",
	"cccd": "id_number",
	"so can cuoc": "id_number",
	"id number": "id_number",
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
	"chien dich": "campaign",
	"campaign": "campaign",
	"campaign name": "campaign",
	"ma chien dich": "campaign_code",
	"campaign code": "campaign_code",
	"campaign_code": "campaign_code",
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
		"id_number",
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
		"campaign",
		"campaign_code",
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
_CSV_REQUIRED_HEADERS = frozenset({"student_name", "phone", "province", "assigned_to"})
_CSV_ATTRIBUTION_HEADERS = frozenset({"campaign", "campaign_code", "source"})
_QUICK_IMPORT_REQUIRED_HEADERS = frozenset(
	{"student_name", "phone", "province", "high_school", "source"}
)
_QUICK_IMPORT_REQUIRED_FIELDS = (
	"student_name",
	"phone",
	"province",
	"high_school",
	"source",
)
MAX_IMPORT_SAMPLE_ROWS = 10
MAX_IMPORT_COLUMNS = 100
_IMPORT_FIELD_DEFINITIONS = (
	{"key": "student_name", "label": "Họ và tên", "required": True, "valueType": "text"},
	{"key": "phone", "label": "Di động", "required": True, "valueType": "text"},
	{"key": "email", "label": "Email", "required": False, "valueType": "text"},
	{"key": "other_email", "label": "Email khác", "required": False, "valueType": "text"},
	{"key": "id_number", "label": "CCCD", "required": False, "valueType": "text"},
	{"key": "gender", "label": "Giới tính", "required": False, "valueType": "text"},
	{"key": "date_of_birth", "label": "Ngày sinh", "required": False, "valueType": "text"},
	{"key": "province", "label": "Tỉnh/Thành phố", "required": True, "valueType": "text"},
	{"key": "ward", "label": "Phường/Xã", "required": False, "valueType": "text"},
	{"key": "high_school", "label": "Trường THPT", "required": True, "valueType": "text"},
	{"key": "major", "label": "Ngành quan tâm", "required": False, "valueType": "text"},
	{"key": "current_grade", "label": "Khối hiện tại", "required": False, "valueType": "text"},
	{"key": "study_stage", "label": "Giai đoạn học tập", "required": False, "valueType": "text"},
	{"key": "advertising_channel", "label": "Kênh quảng cáo", "required": False, "valueType": "text"},
	{"key": "segments", "label": "Phân khúc", "required": False, "valueType": "text"},
	{"key": "admission_year", "label": "Năm tuyển sinh", "required": False, "valueType": "text"},
	{"key": "conversion_potential", "label": "Khả năng chuyển đổi", "required": False, "valueType": "text"},
	{"key": "source", "label": "Nguồn", "required": True, "valueType": "text"},
	{"key": "assigned_to", "label": "Giao cho", "required": False, "valueType": "text"},
	{"key": "branch", "label": "Chi nhánh", "required": False, "valueType": "text"},
	{"key": "tags", "label": "Tags", "required": False, "valueType": "text"},
	{"key": "aspiration", "label": "Nguyện vọng vào FPT", "required": False, "valueType": "text"},
	{"key": "event_participated", "label": "Sự kiện tham gia", "required": False, "valueType": "text"},
	{"key": "description", "label": "Mô tả", "required": False, "valueType": "text"},
	{"key": "notes", "label": "Ghi chú", "required": False, "valueType": "text"},
	{"key": "alt_name", "label": "Tên người liên hệ khác", "required": False, "valueType": "text"},
	{"key": "alt_phone", "label": "Số điện thoại khác", "required": False, "valueType": "text"},
	{"key": "alt_address", "label": "Địa chỉ khác", "required": False, "valueType": "text"},
)
_IMPORT_FIELD_BY_KEY = {item["key"]: item for item in _IMPORT_FIELD_DEFINITIONS}
_IMPORT_SERVER_MANAGED_FIELDS = frozenset(
	{
		"campaign",
		"campaign_code",
		"processing_status",
		"lead_code",
		"resolution",
		"status",
		"student",
		"name",
	}
)

_PUBLIC_LEAD_FIELDS = frozenset(
	{
		"student_name",
		"phone",
		"email",
		"other_email",
		"gender",
		"date_of_birth",
		"source",
		"campaign",
		"campaign_code",
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
		"processing_status",
		"resolution",
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


def _resolve_campaign_code(value: Any) -> str:
	code = _text(value)
	if not code:
		_fail("REQUIRED_FIELD", "campaign_code là bắt buộc.")
	if not is_valid_campaign_code(code):
		_fail(
			"INVALID_CAMPAIGN_CODE",
			"campaign_code phải có dạng CMP-{CAMPUS_CODE}-{YYMMDD}-{TOKEN4} "
			"(hoặc mã legacy CAM-YYYY-NNNNN).",
		)
	campaign = frappe.db.get_value("CRM Campaign", {"stable_code": code}, "name")
	if not campaign:
		_fail("INVALID_CAMPAIGN_CODE", f"Không tìm thấy Campaign với code: {code}.")
	return campaign


def _resolve_quick_import_campaign(value: Any) -> str:
	code = _text(value)
	if not code:
		_fail("CAMPAIGN_REQUIRED", "Campaign là bắt buộc khi import Lead nhanh.")
	code = code.upper()
	if not is_valid_campaign_code(code):
		_fail(
			"INVALID_CAMPAIGN_CODE",
			"campaign_code phải có dạng CMP-{CAMPUS_CODE}-{YYMMDD}-{TOKEN4} "
			"(hoặc mã legacy CAM-YYYY-NNNNN).",
		)
	campaign = frappe.db.get_value(
		"CRM Campaign", {"stable_code": code}, ["name", "status"], as_dict=True
	)
	if not campaign or not campaign.get("name"):
		_fail("INVALID_CAMPAIGN_CODE", f"Không tìm thấy Campaign với code: {code}.")
	if not frappe.has_permission("CRM Campaign", "read", campaign.get("name")):
		_fail("CAMPAIGN_PERMISSION_DENIED", "Bạn không có quyền đọc Campaign đã chọn.")
	status = (_text(campaign.get("status")) or "").upper()
	if status not in _QUICK_IMPORT_CAMPAIGN_STATUSES:
		_fail(
			"CAMPAIGN_STATUS_NOT_ALLOWED",
			"Chỉ Campaign ACTIVE hoặc CLOSED mới được dùng để import Lead.",
		)
	return campaign.get("name")


def _current_admission_year() -> str | None:
	current_year = str(frappe.utils.now_datetime().year)
	return frappe.db.get_value("CRM Admission Year", {"year_name": current_year}, "name")


def _resolve_campaign_reference(value: Any) -> str:
	reference = _text(value)
	if not reference:
		_fail("REQUIRED_FIELD", "campaign hoặc campaign_code là bắt buộc.")
	campaign = resolve_campaign_name(reference)
	if campaign:
		return campaign
	return _resolve_campaign_code(reference)


def _resolve_assignment(
	value: Any, *, allow_unassigned: bool = False, require_staff_name: bool = False
) -> tuple[str | None, str | None, str | None]:
	requested = _text(value)
	if not requested and allow_unassigned:
		return None, None, None
	actor = _text(getattr(frappe.session, "user", None))
	staff = None
	if requested:
		staff = frappe.db.get_value(
			"CRM Staff", requested, ["name", "user", "is_active", "campus"], as_dict=True
		)
		if not staff and not require_staff_name:
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


def _normalize_lead_payload(
	payload: dict[str, Any],
	*,
	allow_unassigned: bool = False,
	require_import_fields: bool = False,
	campaign_name: str | None = None,
) -> tuple[dict[str, Any], list[str], list[str], str | None]:
	name = _text(payload.get("student_name"))
	if not name:
		_fail("REQUIRED_FIELD", "Họ và tên là bắt buộc.")
	if require_import_fields:
		for fieldname, label in (
			("phone", "Di động"),
			("province", "Tỉnh/Thành phố"),
			("high_school", "Trường THPT"),
			("source", "Nguồn"),
		):
			if not _text(payload.get(fieldname)):
				_fail("REQUIRED_FIELD", f"{label} là bắt buộc.")
	phone = _normalize_phone(payload.get("phone"))
	id_number_value = _text(payload.get("id_number"))
	id_number = normalize_national_id(id_number_value) if id_number_value else None
	if id_number_value and not id_number:
		_fail("INVALID_ID_NUMBER", "CCCD phải gồm 9 hoặc 12 chữ số hợp lệ.")
	# A person may submit multiple forms. Duplicate detection belongs to the
	# processing step, where an existing Student or another Lead can be classified
	# as MATCHED/DUPLICATE without rejecting the raw intake event.

	email = _text(payload.get("email"))
	if email:
		email = email.casefold()
	other_email = _text(payload.get("other_email"))
	if other_email:
		other_email = other_email.casefold()
	province_value = _text(payload.get("province"))
	if not province_value:
		_fail("REQUIRED_FIELD", "Tỉnh/Thành phố là bắt buộc.")
	province = _resolve_province(province_value)
	if not frappe.db.exists("CRM Province", province):
		_fail("INVALID_PROVINCE", f"Không tìm thấy Tỉnh/Thành phố: {province_value}.")

	assigned_to, assigned_user, staff_campus = _resolve_assignment(
		payload.get("assigned_to"),
		allow_unassigned=allow_unassigned,
		require_staff_name=require_import_fields,
	)
	branch_value = _text(payload.get("branch")) or staff_campus
	branch = (
		_resolve_link("CRM Campus", branch_value, ("campus_name", "campus_code"), "Chi nhánh")
		if branch_value
		else None
	)

	campaign_value = payload.get("campaign") or payload.get("campaign_code")
	campaign = _resolve_campaign_reference(campaign_value) if campaign_value else None
	source_value = _text(payload.get("source"))
	if campaign_name:
		# Import Lead nhanh: campaign cấp request là nguồn sự thật, không để dữ liệu
		# trong file ghi đè.
		campaign = campaign_name
	if require_import_fields:
		# Import nhanh vẫn yêu cầu Nguồn và lưu Nguồn cùng với Campaign.
		if not source_value:
			_fail("REQUIRED_FIELD", "Nguồn là bắt buộc.")
		source = _resolve_source(source_value)
	else:
		# Legacy: campaign attribution ưu tiên; giữ path source-only nhưng không để
		# source cũ ghi đè Campaign đã liên kết.
		source = _resolve_source(source_value) if source_value and not campaign else None
		if not source and not campaign:
			_fail("REQUIRED_FIELD", "campaign hoặc nguồn là bắt buộc.")

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
	if require_import_fields and not admission_year_value:
		admission_year_value = _current_admission_year()
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
		"id_number": id_number,
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
		"campaign": campaign,
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
	return json.dumps(
		list(dict.fromkeys(item.strip() for item in value)),
		ensure_ascii=False,
		separators=(",", ":"),
	)


def _normalize_public_cccd(payload: dict[str, Any]) -> str | None:
	cccd = _text(payload.get("cccd"))
	id_number = _text(payload.get("id_number"))
	if cccd and id_number and cccd != id_number:
		_fail("INVALID_INPUT", "cccd và id_number phải có cùng giá trị nếu cùng được gửi.")
	return cccd or id_number


def _normalize_public_lead_payload(
	payload: dict[str, Any], *, require_campaign: bool = True
) -> dict[str, Any]:
	name = _text(payload.get("student_name"))
	if not name:
		_fail("REQUIRED_FIELD", "Họ và tên là bắt buộc.")
	campaign_value = payload.get("campaign") or payload.get("campaign_code")
	if campaign_value:
		campaign = _resolve_campaign_reference(campaign_value)
	elif require_campaign:
		# Keep the public API error explicit for existing integrations that send
		# campaign_code rather than the internal Campaign document name.
		campaign = _resolve_campaign_code(payload.get("campaign_code"))
	else:
		campaign = None

	phone_value = _text(payload.get("phone"))
	phone = _normalize_phone(phone_value) if phone_value else None

	email = _text(payload.get("email"))
	if email:
		email = email.casefold()
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
	# Public Campaign intake derives source in the CRM Lead controller. The
	# source field remains accepted here only for backward-compatible envelopes.
	source = _resolve_source(source_value) if source_value and not campaign else None
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
	id_number_value = _text(payload.get("id_number"))
	id_number = normalize_national_id(id_number_value) if id_number_value else None
	if id_number_value and not id_number:
		_fail("INVALID_ID_NUMBER", "CCCD phải gồm 9 hoặc 12 chữ số hợp lệ.")
	return {
		"student_name": name,
		"phone": phone,
		"email": email,
		"other_email": other_email,
		"gender": _text(payload.get("gender")),
		"date_of_birth": _text(payload.get("date_of_birth")),
		"source": source,
		"campaign": campaign,
		"advertising_channel": _text(payload.get("advertising_channel")),
		"import_source_id": _text(payload.get("import_source_id")),
		"segments": _normalize_public_segments(payload.get("segments")),
		"assignment_priority": assignment_priority,
		"branch": branch,
		"id_number": id_number,
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


def _create_lead(
	fields: dict[str, Any],
	*,
	allow_unassigned: bool = False,
	require_import_fields: bool = False,
	campaign_name: str | None = None,
) -> dict[str, Any]:
	values, tags, events, assigned_user = _normalize_lead_payload(
		fields,
		allow_unassigned=allow_unassigned,
		require_import_fields=require_import_fields,
		campaign_name=campaign_name,
	)
	doc = frappe.get_doc({"doctype": "CRM Lead", **values})
	doc.check_permission("create")
	doc.insert()
	_apply_tags(doc, tags)
	event_result = _record_events(doc.name, events)
	if (
		(not allow_unassigned and not doc.get("assigned_to"))
		or not doc.get("phone")
		or not doc.get("province")
		or not doc.get("source")
	):
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
				"processing_status",
				"resolution",
				"conversion_blockers",
				"student_name",
				"phone",
				"id_number",
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
				"campaign",
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
	doc.insert(ignore_permissions=True)
	return {
		"doctype": "CRM Lead",
		"name": doc.name,
		"lead_code": doc.get("lead_code"),
		"leadCode": doc.get("lead_code"),
		"processing_status": doc.get("processing_status"),
		"resolution": doc.get("resolution"),
		"conversion_blockers": doc.get("conversion_blockers"),
		"campaign": doc.get("campaign"),
		"campaign_code": fields.get("campaign_code"),
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
	# Frappe injects the routed method name as ``cmd`` into form_dict. It is
	# transport metadata, not a client field, and must not make guest payloads
	# fail the public field allowlist.
	payload.pop("cmd", None)
	if fields is not None and payload:
		_fail("INVALID_INPUT", "Gửi fields hoặc các field trực tiếp, không gửi cả hai.")
	return _create_public_lead(_parse_public_payload(fields if fields is not None else payload))


def _public_lookup_response(
	rows: list[Any], label_field: str, code_field: str | None = None, extra_fields: tuple[str, ...] = ()
) -> dict[str, Any]:
	items = []
	for row in rows:
		item = {"value": row.get("name"), "label": row.get(label_field)}
		if code_field:
			item["code"] = row.get(code_field)
		for fieldname in extra_fields:
			item[fieldname] = row.get(fieldname)
		items.append(item)
	return {"items": items, "total": len(items)}


def _get_public_link_label_map(doctype: str, values: set[str], label_field: str) -> dict[str, Any]:
	if not values:
		return {}
	rows = frappe.get_all(
		doctype,
		filters={"name": ["in", sorted(values)]},
		fields=["name", label_field],
		limit_page_length=0,
	)
	return {row.get("name"): row.get(label_field) for row in rows}


def _normalize_public_lead_links(rows: list[Any]) -> list[dict[str, Any]]:
	label_maps = {}
	for fieldname, (doctype, label_field) in _PUBLIC_LEAD_LINK_LABELS.items():
		values = {row.get(fieldname) for row in rows if row.get(fieldname)}
		label_maps[fieldname] = _get_public_link_label_map(doctype, values, label_field)

	normalized_rows = []
	for row in rows:
		lead = dict(row)
		for fieldname, labels in label_maps.items():
			value = lead.get(fieldname)
			label = labels.get(value)
			if label:
				lead[fieldname] = label
		normalized_rows.append(lead)
	return normalized_rows


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=120, seconds=60)
def get_public_provinces() -> dict[str, Any]:
	"""Return provinces for the public admission form."""
	rows = frappe.get_all(
		"CRM Province",
		fields=["name", "province_name", "province_code"],
		order_by="province_name asc, name asc",
		limit_page_length=0,
	)
	return _public_lookup_response(rows, "province_name", "province_code")


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=120, seconds=60)
def get_public_wards(province: str | None = None) -> dict[str, Any]:
	"""Return wards scoped to one province for the public admission form."""
	province_value = _text(province)
	if not province_value:
		_fail("REQUIRED_FIELD", "province là bắt buộc.")
	province_name = resolve_province(province_value)
	if not frappe.db.exists("CRM Province", province_name):
		_fail("INVALID_PROVINCE", f"Không tìm thấy Tỉnh/Thành phố: {province_value}.")

	rows = frappe.get_all(
		"CRM Ward",
		filters={"province": province_name},
		fields=["name", "ward_name", "ward_code", "ward_type", "province"],
		order_by="ward_name asc, name asc",
		limit_page_length=0,
	)
	return _public_lookup_response(rows, "ward_name", "ward_code", ("ward_type", "province"))


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=120, seconds=60)
def get_public_high_schools(ward: str | None = None) -> dict[str, Any]:
	"""Return active high schools scoped to one ward for the public form."""
	ward_value = _text(ward)
	if not ward_value:
		_fail("REQUIRED_FIELD", "ward là bắt buộc.")
	ward_name = resolve_ward(ward_value)
	if not frappe.db.exists("CRM Ward", ward_name):
		_fail("INVALID_WARD", f"Không tìm thấy Xã/Phường: {ward_value}.")

	rows = frappe.get_all(
		"CRM High School",
		filters={"ward": ward_name, "is_active": 1},
		fields=["name", "school_name", "school_code", "school_type", "province", "ward"],
		order_by="school_name asc, name asc",
		limit_page_length=0,
	)
	return _public_lookup_response(rows, "school_name", "school_code", ("school_type", "province", "ward"))


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=120, seconds=60)
def get_public_majors() -> dict[str, Any]:
	"""Return active majors for the public admission form."""
	rows = frappe.get_all(
		"CRM Major",
		filters={"is_active": 1},
		fields=["name", "major_name", "major_code", "degree_name", "major_group"],
		order_by="major_name asc, name asc",
		limit_page_length=0,
	)
	return _public_lookup_response(rows, "major_name", "major_code", ("degree_name", "major_group"))


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=120, seconds=60)
def get_public_leads(
	campaign_code: str | None = None,
	startdate: str | None = None,
	enddate: str | None = None,
	start_date: str | None = None,
	end_date: str | None = None,
	start: int | str = 0,
	page_length: int | str = 20,
) -> dict[str, Any]:
	"""Return a public, non-sensitive Lead list scoped to one campaign code."""
	campaign_name = _resolve_campaign_code(campaign_code)
	start_value = _parse_public_date(
		_coalesce_public_date(startdate, start_date, "startdate/start_date"), "startdate"
	)
	end_value = _parse_public_date(_coalesce_public_date(enddate, end_date, "enddate/end_date"), "enddate")
	if start_value and end_value and start_value > end_value:
		_fail("INVALID_DATE", "startdate không được lớn hơn enddate.")

	start = _parse_public_int(start, "start", default=0, minimum=0)
	page_length = _parse_public_int(
		page_length,
		"page_length",
		default=20,
		minimum=1,
		maximum=MAX_PUBLIC_LEAD_PAGE_LENGTH,
	)

	filters: list[list[Any]] = [["campaign", "=", campaign_name]]
	if start_value:
		filters.append(["creation", ">=", f"{start_value} 00:00:00"])
	if end_value:
		filters.append(["creation", "<", f"{end_value + timedelta(days=1)} 00:00:00"])

	rows = frappe.get_all(
		"CRM Lead",
		filters=filters,
		fields=list(PUBLIC_LEAD_LIST_FIELDS),
		order_by="creation desc, name desc",
		limit_start=start,
		limit_page_length=page_length,
	)
	return {
		"total": frappe.db.count("CRM Lead", filters=filters),
		"start": start,
		"page_length": page_length,
		"leads": _normalize_public_lead_links(rows),
	}


_SERVER_MANAGED_IMPORT_HEADERS = frozenset(
	{
		"tinh trang lead",
		"lead status",
		"conversion status",
		"enrollment status",
		"lifecycle stage",
	}
)


def _json_safe_import_value(value: Any) -> str | None:
	if value is None:
		return None
	if isinstance(value, datetime):
		if value.time() == time.min:
			return value.date().isoformat()
		return value.isoformat(sep=" ")
	if isinstance(value, date | time):
		return value.isoformat()
	if isinstance(value, float) and not math.isfinite(value):
		return None
	if isinstance(value, bool):
		return "true" if value else "false"
	return str(value)


def _has_import_value(values: Iterable[Any]) -> bool:
	return any(_text(_json_safe_import_value(value)) for value in values)


def _pad_import_row(values: Iterable[Any], width: int) -> list[Any]:
	row = list(values)
	return row[:width] + [None] * max(0, width - len(row))


def _check_import_column_count(headers: list[Any]) -> None:
	if len(headers) > MAX_IMPORT_COLUMNS:
		_fail("TOO_MANY_COLUMNS", f"File import tối đa {MAX_IMPORT_COLUMNS} cột.")


def _parse_raw_csv_table(csv_content: str) -> dict[str, Any]:
	if not isinstance(csv_content, str) or not csv_content.strip():
		_fail("INVALID_CSV", "csv_content không được rỗng.")

	reader = csv.reader(io.StringIO(csv_content.lstrip("\ufeff")))
	headers: list[str] | None = None
	data_rows: list[dict[str, Any]] = []
	for physical_row, values in enumerate(reader, start=1):
		if headers is None:
			if not _has_import_value(values):
				continue
			headers = [_json_safe_import_value(value) or "" for value in values]
			_check_import_column_count(headers)
			continue
		if not _has_import_value(values):
			continue
		if len(data_rows) >= MAX_IMPORT_ROWS:
			_fail("CSV_TOO_LARGE", f"CSV tối đa {MAX_IMPORT_ROWS} dòng.")
		data_rows.append({"row": physical_row, "values": _pad_import_row(values, len(headers))})

	if headers is None:
		_fail("INVALID_CSV", "CSV không có header.")
	if not data_rows:
		_fail("INVALID_CSV", "CSV không có dòng dữ liệu.")
	return {"headers": headers, "rows": data_rows}


def _parse_raw_xlsx_table(file_content: bytes) -> dict[str, Any]:
	try:
		from openpyxl import load_workbook
	except ImportError:
		_fail("XLSX_UNAVAILABLE", "Máy chủ chưa cài thư viện đọc file XLSX.")

	workbook = None
	try:
		workbook = load_workbook(io.BytesIO(file_content), read_only=True, data_only=True)
		worksheet = workbook.worksheets[0] if workbook.worksheets else None
		if worksheet is None:
			_fail("INVALID_XLSX", "File XLSX không có worksheet.")

		headers: list[str] | None = None
		data_rows: list[dict[str, Any]] = []
		for physical_row, values in enumerate(worksheet.iter_rows(values_only=True), start=1):
			values = list(values)
			if headers is None:
				if not _has_import_value(values):
					continue
				headers = [_json_safe_import_value(value) or "" for value in values]
				_check_import_column_count(headers)
				continue
			if not _has_import_value(values):
				continue
			if len(data_rows) >= MAX_IMPORT_ROWS:
				_fail("XLSX_TOO_LARGE", f"XLSX tối đa {MAX_IMPORT_ROWS} dòng.")
			data_rows.append({"row": physical_row, "values": _pad_import_row(values, len(headers))})

		if headers is None:
			_fail("INVALID_XLSX", "XLSX không có header.")
		if not data_rows:
			_fail("INVALID_XLSX", "XLSX không có dòng dữ liệu.")
		return {"headers": headers, "rows": data_rows}
	except LeadMappingError:
		raise
	except Exception:
		_fail("INVALID_XLSX", "Không thể đọc file XLSX.")
	finally:
		if workbook is not None:
			workbook.close()


def _prepare_import_file(file_content: bytes | str, filename: str) -> tuple[bytes, str]:
	if isinstance(file_content, str):
		file_content = file_content.encode("utf-8")
	if not isinstance(file_content, bytes) or not file_content:
		_fail("INVALID_FILE", "File import không được rỗng.")
	if len(file_content) > MAX_IMPORT_FILE_BYTES:
		_fail("FILE_TOO_LARGE", "File import tối đa 5 MB.")
	return file_content, Path(str(filename or "")).suffix.casefold()


def _parse_raw_import_file(file_content: bytes | str, filename: str) -> dict[str, Any]:
	file_content, file_extension = _prepare_import_file(file_content, filename)
	if file_extension == ".csv":
		try:
			csv_content = file_content.decode("utf-8-sig")
		except UnicodeDecodeError:
			_fail("INVALID_CSV", "CSV phải sử dụng mã hóa UTF-8.")
		return _parse_raw_csv_table(csv_content)
	if file_extension == ".xlsx":
		return _parse_raw_xlsx_table(file_content)
	_fail("UNSUPPORTED_FILE", "Chỉ hỗ trợ file CSV hoặc XLSX.")


def _infer_import_field(header: str) -> str | None:
	candidate = _HEADER_ALIASES.get(_normalize_header(header))
	return candidate if candidate in _IMPORT_FIELD_BY_KEY else None


def _parse_column_mapping(value: list[dict[str, Any]] | str | None) -> list[dict[str, Any]]:
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			_fail("INVALID_COLUMN_MAPPING", "column_mapping phải là JSON array hợp lệ.")
	if not isinstance(value, list) or not value:
		_fail("INVALID_COLUMN_MAPPING", "column_mapping phải là array không rỗng.")

	parsed: list[dict[str, Any]] = []
	for item in value:
		if not isinstance(item, dict):
			_fail("INVALID_COLUMN_MAPPING", "Mỗi mapping phải là object.")
		source_index = item.get("sourceIndex", item.get("source_index"))
		if isinstance(source_index, bool) or not isinstance(source_index, int) or source_index < 0:
			_fail("INVALID_SOURCE_INDEX", "sourceIndex phải là số nguyên không âm.")
		target_field = item.get("targetField", item.get("target_field"))
		if target_field is not None:
			target_field = _text(target_field)
		enabled = item.get("enabled", True)
		if not isinstance(enabled, bool):
			_fail("INVALID_COLUMN_MAPPING", "enabled phải là boolean.")
		parsed.append(
			{"sourceIndex": source_index, "targetField": target_field, "enabled": enabled}
		)
	return parsed


def _validate_column_mapping(
	value: list[dict[str, Any]] | str | None,
	header_count: int,
	*,
	require_required: bool = True,
) -> list[dict[str, Any]]:
	mapping = _parse_column_mapping(value)
	seen_sources: set[int] = set()
	seen_targets: set[str] = set()
	for item in mapping:
		source_index = item["sourceIndex"]
		if source_index >= header_count:
			_fail("INVALID_SOURCE_INDEX", f"Không tìm thấy sourceIndex: {source_index}.")
		if source_index in seen_sources:
			_fail("DUPLICATE_SOURCE_INDEX", f"sourceIndex bị lặp: {source_index}.")
		seen_sources.add(source_index)

		target_field = item["targetField"]
		if target_field is None:
			if item["enabled"]:
				_fail("MAPPING_TARGET_REQUIRED", "Cột đang bật phải có targetField.")
			continue
		if target_field in _IMPORT_SERVER_MANAGED_FIELDS:
			_fail("SERVER_MANAGED_FIELD", f"Không được mapping field server-managed: {target_field}.")
		if target_field not in _IMPORT_FIELD_BY_KEY:
			_fail("UNKNOWN_FIELD", f"Field import không được hỗ trợ: {target_field}.")
		if item["enabled"]:
			if target_field in seen_targets:
				_fail("DUPLICATE_TARGET_FIELD", f"Target field bị lặp: {target_field}.")
			seen_targets.add(target_field)

	if require_required:
		missing = [field for field in _QUICK_IMPORT_REQUIRED_FIELDS if field not in seen_targets]
		if missing:
			_fail("MISSING_REQUIRED_MAPPING", f"Thiếu mapping bắt buộc: {', '.join(missing)}.")
	return mapping


def _mapped_import_rows(
	table: dict[str, Any], column_mapping: list[dict[str, Any]] | str | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
	headers = table["headers"]
	mapping = _validate_column_mapping(column_mapping, len(headers))
	entries = []
	for raw_row in table["rows"]:
		values = raw_row["values"]
		fields = {
			item["targetField"]: _json_safe_import_value(values[item["sourceIndex"]])
			for item in mapping
			if item["enabled"] and item["targetField"] is not None
		}
		entries.append({"row": raw_row["row"], "fields": fields})
	enabled_sources = {item["sourceIndex"] for item in mapping if item["enabled"]}
	return entries, {
		"mappedFields": [item["targetField"] for item in mapping if item["enabled"]],
		"ignoredColumns": [
			{"sourceIndex": index, "label": label}
			for index, label in enumerate(headers)
			if index not in enabled_sources
		],
	}


def _request_form_value(fieldname: str) -> Any:
	form_dict = getattr(frappe, "form_dict", None)
	return form_dict.get(fieldname) if form_dict is not None else None


def _has_uploaded_import_file() -> bool:
	try:
		request = getattr(frappe, "request", None)
	except RuntimeError:
		return False
	files = getattr(request, "files", None)
	return bool(files is not None and files.get("file") is not None)


@frappe.whitelist(methods=["POST"])
def inspect_lead_import() -> dict[str, Any]:
	"""Inspect an import file without requiring canonical headers or writing Leads."""
	_require_authenticated()
	_require_lead_create_permission()
	campaign_code = _request_form_value("campaign_code")
	if _text(campaign_code):
		_resolve_quick_import_campaign(campaign_code)
	file_content, filename = _uploaded_import_file()
	table = _parse_raw_import_file(file_content, filename)
	return {
		"filename": filename,
		"fieldCatalog": [dict(item) for item in _IMPORT_FIELD_DEFINITIONS],
		"headers": [
			{
				"sourceIndex": index,
				"label": label,
				"inferredField": _infer_import_field(label),
				"enabled": bool(_infer_import_field(label)),
			}
			for index, label in enumerate(table["headers"])
		],
		"sampleRows": [
			{
				"row": row["row"],
				"values": [_json_safe_import_value(value) for value in row["values"]],
			}
			for row in table["rows"][:MAX_IMPORT_SAMPLE_ROWS]
		],
		"requiredFields": list(_QUICK_IMPORT_REQUIRED_FIELDS),
	}


def _canonical_import_headers(
	headers: Iterable[Any],
	required_headers: frozenset[str],
	*,
	reject_server_managed: bool = True,
) -> dict[Any, str]:
	canonical_headers = {}
	for header in headers:
		normalized = _normalize_header(header)
		if normalized == "campaign":
			_fail("UNKNOWN_FIELD", f"Unsupported field: {header}.")
		if normalized in _SERVER_MANAGED_IMPORT_HEADERS:
			if reject_server_managed:
				_fail("UNKNOWN_FIELD", f"Unsupported field: {header}.")
			continue
		canonical = _HEADER_ALIASES.get(normalized)
		if canonical:
			canonical_headers[header] = canonical
	missing = sorted(required_headers - set(canonical_headers.values()))
	if missing:
		_fail("CSV_MISSING_HEADERS", f"CSV thiếu cột bắt buộc: {', '.join(missing)}.")
	return canonical_headers


def _parse_csv_rows(
	csv_content: str,
	*,
	required_headers: frozenset[str] = _CSV_REQUIRED_HEADERS,
) -> list[dict[str, Any]]:
	if not isinstance(csv_content, str) or not csv_content.strip():
		_fail("INVALID_CSV", "csv_content không được rỗng.")
	reader = csv.DictReader(io.StringIO(csv_content.lstrip("\ufeff")))
	if not reader.fieldnames:
		_fail("INVALID_CSV", "CSV không có header.")
	canonical_headers = _canonical_import_headers(
		reader.fieldnames,
		required_headers,
		reject_server_managed=required_headers != _QUICK_IMPORT_REQUIRED_HEADERS,
	)
	if not _CSV_ATTRIBUTION_HEADERS.intersection(canonical_headers.values()):
		_fail("CSV_MISSING_HEADERS", "CSV cần cột Campaign (hoặc campaign_code).")
	rows = []
	for row in reader:
		mapped = {
			canonical_headers[header]: value for header, value in row.items() if header in canonical_headers
		}
		if any(_text(value) for value in mapped.values()):
			if len(rows) >= MAX_IMPORT_ROWS:
				_fail("CSV_TOO_LARGE", f"CSV tối đa {MAX_IMPORT_ROWS} dòng.")
			rows.append(mapped)
	if not rows:
		_fail("INVALID_CSV", "CSV không có dòng dữ liệu.")
	return rows


def _parse_xlsx_rows(
	file_content: bytes,
	*,
	required_headers: frozenset[str] = _QUICK_IMPORT_REQUIRED_HEADERS,
) -> list[dict[str, Any]]:
	try:
		from openpyxl import load_workbook
	except ImportError:
		_fail("XLSX_UNAVAILABLE", "Máy chủ chưa cài thư viện đọc file XLSX.")

	workbook = None
	try:
		workbook = load_workbook(io.BytesIO(file_content), read_only=True, data_only=True)
		worksheet = workbook.worksheets[0] if workbook.worksheets else None
		if worksheet is None:
			_fail("INVALID_XLSX", "File XLSX không có worksheet.")
		rows = worksheet.iter_rows(values_only=True)
		headers = None
		for values in rows:
			candidate_headers = list(values)
			canonical_values = {
				_HEADER_ALIASES.get(_normalize_header(header))
				for header in candidate_headers
				if _HEADER_ALIASES.get(_normalize_header(header))
			}
			if required_headers.issubset(canonical_values):
				headers = candidate_headers
				break
		if headers is None:
			_fail("CSV_MISSING_HEADERS", "XLSX thiếu cột bắt buộc.")
		canonical_headers = _canonical_import_headers(
			headers,
			required_headers,
			reject_server_managed=required_headers != _QUICK_IMPORT_REQUIRED_HEADERS,
		)
		mapped_rows = []
		for values in rows:
			mapped = {
				canonical_headers[header]: value
				for header, value in zip(headers, values, strict=False)
				if header in canonical_headers
			}
			if any(_text(value) for value in mapped.values()):
				if len(mapped_rows) >= MAX_IMPORT_ROWS:
					_fail("XLSX_TOO_LARGE", f"XLSX tối đa {MAX_IMPORT_ROWS} dòng.")
				mapped_rows.append(mapped)
		if not mapped_rows:
			_fail("INVALID_XLSX", "XLSX không có dòng dữ liệu.")
		return mapped_rows
	except LeadMappingError:
		raise
	except Exception:
		_fail("INVALID_XLSX", "Không thể đọc file XLSX.")
	finally:
		if workbook is not None:
			workbook.close()


def _parse_import_file(
	file_content: bytes | str,
	filename: str,
	required_headers: frozenset[str] = _QUICK_IMPORT_REQUIRED_HEADERS,
) -> list[dict[str, Any]]:
	file_content, file_extension = _prepare_import_file(file_content, filename)
	if file_extension == ".csv":
		try:
			csv_content = file_content.decode("utf-8-sig")
		except UnicodeDecodeError:
			_fail("INVALID_CSV", "CSV phải sử dụng mã hóa UTF-8.")
		return _parse_csv_rows(csv_content, required_headers=required_headers)
	if file_extension == ".xlsx":
		return _parse_xlsx_rows(file_content, required_headers=required_headers)
	_fail("UNSUPPORTED_FILE", "Chỉ hỗ trợ file CSV hoặc XLSX.")


def _parse_import_rows(
	rows: list[dict[str, Any]] | str | None,
	csv_content: str | None,
	*,
	required_headers: frozenset[str] = _CSV_REQUIRED_HEADERS,
) -> list[dict[str, Any]]:
	if csv_content is not None:
		return _parse_csv_rows(csv_content, required_headers=required_headers)
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
		# error.message giữ câu thuần, str(error) lại kèm tiền tố "CODE: ".
		return {"code": error.code, "message": error.message}
	return {"code": "IMPORT_ROW_FAILED", "message": str(error)}


def _import_mode(value: Any) -> str:
	mode = _text(value) or "legacy"
	if mode not in _IMPORT_MODES:
		_fail("INVALID_IMPORT_MODE", "Import mode không được hỗ trợ.")
	return mode


def _uploaded_import_file() -> tuple[bytes, str]:
	request = getattr(frappe, "request", None)
	files = getattr(request, "files", None)
	upload = files.get("file") if files is not None else None
	if upload is None:
		_fail("FILE_REQUIRED", "Vui lòng chọn file import.")
	filename = Path(str(getattr(upload, "filename", "") or "")).name
	content_length = getattr(upload, "content_length", None)
	try:
		if content_length is not None and int(content_length) > MAX_IMPORT_FILE_BYTES:
			_fail("FILE_TOO_LARGE", "File import tối đa 5 MB.")
	except (TypeError, ValueError):
		pass
	stream = getattr(upload, "stream", upload)
	try:
		content = stream.read(MAX_IMPORT_FILE_BYTES + 1)
	except TypeError:
		# Keep lightweight upload doubles compatible with the contract tests.
		content = upload.read()
	if isinstance(content, bytes) and len(content) > MAX_IMPORT_FILE_BYTES:
		_fail("FILE_TOO_LARGE", "File import tối đa 5 MB.")
	if not isinstance(content, bytes):
		_fail("INVALID_FILE", "Nội dung file import không hợp lệ.")
	return content, filename


def _preview_fields(values: dict[str, Any]) -> dict[str, Any]:
	return {
		key: value
		for key, value in values.items()
		if key not in {"campaign", "campaign_code"}
	}


@frappe.whitelist(methods=["POST"])
def preview_lead_import() -> dict[str, Any]:
	"""Validate a quick-import file without inserting any Lead."""
	_require_authenticated()
	_require_lead_create_permission()
	campaign_code = _request_form_value("campaign_code")
	campaign_name = (
		_resolve_quick_import_campaign(campaign_code) if _text(campaign_code) else None
	)
	file_content, filename = _uploaded_import_file()
	column_mapping = _request_form_value("column_mapping")
	mapped_metadata = None
	if _text(column_mapping):
		table = _parse_raw_import_file(file_content, filename)
		parsed_rows, mapped_metadata = _mapped_import_rows(table, column_mapping)
	else:
		parsed_rows = [
			{"row": index, "fields": row}
			for index, row in enumerate(_parse_import_file(file_content, filename), start=2)
		]
	preview_rows = []
	errors = []
	for parsed_row in parsed_rows:
		index = parsed_row["row"]
		row = parsed_row["fields"]
		try:
			preview_row = {
				key: value for key, value in row.items() if key != "campaign_code"
			}
			values, _tags, _events, _assigned_user = _normalize_lead_payload(
				preview_row,
				allow_unassigned=True,
				require_import_fields=True,
				campaign_name=campaign_name,
			)
			preview_rows.append({"row": index, "fields": _preview_fields(values), "errors": []})
		except Exception as error:
			row_error = {"row": index, **_row_error(error)}
			errors.append(row_error)
			preview_rows.append({"row": index, "fields": {}, "errors": [row_error]})
	response = {
		"filename": filename,
		"total": len(parsed_rows),
		"valid": len(parsed_rows) - len(errors),
		"failed": len(errors),
		"rows": preview_rows,
		"errors": errors,
	}
	if mapped_metadata is not None:
		response.update(mapped_metadata)
	return response


@frappe.whitelist(methods=["POST"])
def import_leads(
	rows: list[dict[str, Any]] | str | None = None,
	csv_content: str | None = None,
	filename: str | None = None,
	import_mode: str = "legacy",
	campaign_code: str | None = None,
	column_mapping: list[dict[str, Any]] | str | None = None,
) -> dict[str, Any]:
	"""Import CSV-compatible Leads with savepoint isolation per row."""
	_require_authenticated()
	mode = _import_mode(import_mode)
	quick_import = mode == "quick_create"
	if quick_import:
		_require_lead_create_permission()
	request_mapping = _request_form_value("column_mapping")
	if quick_import and (column_mapping is not None or _text(request_mapping)):
		if not _has_uploaded_import_file():
			_fail("FILE_REQUIRED", "Vui lòng chọn file import.")
		file_content, uploaded_filename = _uploaded_import_file()
		mapping_value = column_mapping if column_mapping is not None else request_mapping
		if not _text(mapping_value):
			_fail("COLUMN_MAPPING_REQUIRED", "column_mapping là bắt buộc khi import file.")
		table = _parse_raw_import_file(file_content, uploaded_filename)
		parsed_rows, _mapped_metadata = _mapped_import_rows(table, mapping_value)
		filename = filename or uploaded_filename
	else:
		parsed_rows = [
			{"row": index, "fields": row}
			for index, row in enumerate(
				_parse_import_rows(
					rows,
					csv_content,
					required_headers=_QUICK_IMPORT_REQUIRED_HEADERS if quick_import else _CSV_REQUIRED_HEADERS,
				),
				start=2,
			)
		]
	campaign_name = _resolve_quick_import_campaign(campaign_code) if quick_import else None
	created = []
	errors = []
	for parsed_row in parsed_rows:
		index = parsed_row["row"]
		row = parsed_row["fields"]
		savepoint = f"lead_mapping_row_{index}"
		frappe.db.savepoint(savepoint)
		try:
			created.append(
				{
					"row": index,
					**_create_lead(
						row,
						allow_unassigned=quick_import,
						require_import_fields=quick_import,
						campaign_name=campaign_name,
					),
				}
			)
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
