from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

import frappe
from frappe import _

from crm.fcrm.role_policy import (
	CANONICAL_PROFILE_ROLES,
	DESK_MANAGEMENT_ROLE_NAMES,
	FRAMEWORK_ROLE_NAMES,
	LEGACY_OVERLAY_ROLES,
	LEGACY_UNMAPPED_ROLES,
	ROLE_BACKFILL_SOURCES,
	classify_role_set,
	resolve_crm_profile,
)

AVAILABILITY_STATES = frozenset({"available", "partial", "unavailable"})
REGIONS = frozenset({"all", "north", "central", "highlands", "south", "mekong"})
METRICS = frozenset({"opportunity", "leads", "conversion", "competition", "revenue"})
_EXTERNAL_SCHOOL_ID = re.compile(r"^(?P<province>\d{2})-(?P<middle>\d+)-(?P<school>\d{3})$")
_SCHOOL_FIELDS = [
	"name",
	"school_name",
	"school_code",
	"school_type",
	"school_area",
	"school_tier",
	"boarding_type",
	"province",
	"ward",
	"latitude",
	"longitude",
	"address",
	"is_key_account",
]


def _set_error(code: str, message: str, status: int) -> None:
	try:
		if getattr(frappe, "local", None) and isinstance(getattr(frappe.local, "response", None), dict):
			frappe.local.response["error"] = {"code": code, "message": message}
			frappe.local.response["http_status_code"] = status
	except (AttributeError, TypeError):
		pass


def raise_api_error(code: str, message: str, exception: type[Exception], status: int) -> None:
	_set_error(code, message, status)
	frappe.throw(_(message), exception)


def require_director_access() -> dict[str, Any]:
	"""Authorize one active, canonical Director endpoint identity."""
	user = getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		raise_api_error("UNAUTHENTICATED", "Bạn cần đăng nhập để truy cập dữ liệu này.", frappe.AuthenticationError, 401)

	enabled = frappe.db.get_value("User", user, "enabled")
	if enabled not in (1, True, "1"):
		raise_api_error("UNAUTHENTICATED", "Tài khoản không hoạt động.", frappe.AuthenticationError, 401)

	roles = frozenset(frappe.get_roles(user))
	if user == "Administrator":
		return {"user": user, "profile": "platform_superuser", "roleState": "platform_superuser"}

	classification = classify_role_set(roles)
	profile = resolve_crm_profile(roles)
	approved_director = classification == "canonical_profile" and profile == "admissions_director"
	allowed_system_roles = FRAMEWORK_ROLE_NAMES | frozenset(DESK_MANAGEMENT_ROLE_NAMES) | {"System Manager"}
	approved_system_manager = classification == "system_manager" and not (roles - allowed_system_roles)
	forbidden_business_roles = CANONICAL_PROFILE_ROLES | LEGACY_OVERLAY_ROLES | LEGACY_UNMAPPED_ROLES | ROLE_BACKFILL_SOURCES
	if classification == "system_manager" and roles & (forbidden_business_roles - {"System Manager"}):
		approved_system_manager = False
	if not (approved_director or approved_system_manager):
		raise_api_error("FORBIDDEN", "Bạn không có quyền truy cập dữ liệu Director.", frappe.PermissionError, 403)
	return {"user": user, "profile": profile or "system_manager", "roleState": classification}


def parse_admission_year(value: Any, *, required: bool = True) -> str | None:
	if value in (None, ""):
		if required:
			raise_api_error("INVALID_ADMISSION_YEAR", "Kỳ tuyển sinh không hợp lệ.", frappe.ValidationError, 422)
		return None
	text = str(value).strip()
	if not re.fullmatch(r"\d{4}", text) or not 2000 <= int(text) <= 2100:
		raise_api_error("INVALID_ADMISSION_YEAR", "Kỳ tuyển sinh không hợp lệ.", frappe.ValidationError, 422)
	return text


def resolve_admission_year(value: Any = None) -> str:
	if value not in (None, ""):
		return parse_admission_year(value)
	rows = frappe.get_list(
		"CRM Admission Year",
		filters={"is_active": 1},
		fields=["name", "year_name"],
		order_by="year_name desc, name desc",
		limit_page_length=2,
	)
	if len(rows) != 1:
		raise_api_error("INVALID_ADMISSION_YEAR", "Cần cấu hình đúng một kỳ tuyển sinh đang hoạt động.", frappe.ValidationError, 422)
	return parse_admission_year(rows[0].get("year_name") or rows[0].get("name"))


def parse_enum(value: Any, *, field: str, allowed: Iterable[str], default: str | None = None) -> str:
	text = default if value in (None, "") else str(value).strip().lower()
	if text not in frozenset(allowed):
		raise_api_error("INVALID_QUERY", f"Tham số {field} không hợp lệ.", frappe.ValidationError, 400)
	return str(text)


def parse_boolean(value: Any, *, field: str, default: bool | None = None) -> bool:
	if value in (None, "") and default is not None:
		return default
	if value is True or (isinstance(value, str) and value.strip().casefold() == "true"):
		return True
	if value is False or (isinstance(value, str) and value.strip().casefold() == "false"):
		return False
	return raise_api_error("INVALID_QUERY", f"Tham số {field} phải là boolean.", frappe.ValidationError, 400)


def parse_limit(value: Any, *, field: str, minimum: int, maximum: int, default: int | None = None) -> int:
	if value in (None, "") and default is not None:
		return default
	if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value or "").strip()):
		raise_api_error("INVALID_QUERY", f"Tham số {field} không hợp lệ.", frappe.ValidationError, 400)
	number = int(value)
	if not minimum <= number <= maximum:
		raise_api_error("INVALID_QUERY", f"Tham số {field} không hợp lệ.", frappe.ValidationError, 400)
	return number


def parse_school_id(school_id: Any) -> tuple[str, str, str, str]:
	if not isinstance(school_id, str) or not school_id.strip() or len(school_id) > 64:
		raise_api_error("INVALID_SCHOOL_ID", "Mã trường không hợp lệ.", frappe.ValidationError, 400)
	match = _EXTERNAL_SCHOOL_ID.fullmatch(school_id.strip())
	if not match:
		raise_api_error("SCHOOL_NOT_FOUND", "Không tìm thấy trường.", frappe.DoesNotExistError, 404)
	middle = match.group("middle")
	# Legacy links used two-digit district codes. Current canonical datasets may
	# use five- or seven-digit ward codes after administrative-code updates.
	mode = "legacy" if len(middle) == 2 else "canonical"
	return match.group("province"), middle, match.group("school"), mode


def _unique_visible(doctype: str, *, filters: dict[str, Any], fields: list[str]) -> dict[str, Any]:
	rows = frappe.get_list(
		doctype,
		filters=filters,
		fields=fields,
		order_by="name asc",
		limit_page_length=2,
	)
	if len(rows) != 1:
		raise_api_error("SCHOOL_NOT_FOUND", "Không tìm thấy trường.", frappe.DoesNotExistError, 404)
	return dict(rows[0])


def resolve_school_id(school_id: Any) -> dict[str, Any]:
	province_code, middle_code, school_code, mode = parse_school_id(school_id)
	province = _unique_visible(
		"CRM Province", filters={"province_code": province_code}, fields=["name"]
	)
	school_code_values = [school_code, school_code.lstrip("0") or "0"]
	filters = {"province": province["name"], "school_code": ["in", list(dict.fromkeys(school_code_values))]}
	if mode == "canonical":
		ward = _unique_visible(
			"CRM Ward",
			filters={"province": province["name"], "ward_code": middle_code},
			fields=["name", "ward_code"],
		)
		filters["ward"] = ward["name"]
	school = _unique_visible("CRM High School", filters=filters, fields=_SCHOOL_FIELDS)
	ward_code = middle_code if mode == "canonical" else None
	if mode == "legacy" and school.get("ward"):
		ward_rows = frappe.get_list(
			"CRM Ward",
			filters={"name": school.get("ward"), "province": province["name"]},
			fields=["ward_code"],
			order_by="name asc",
			limit_page_length=1,
		)
		ward_code = ward_rows[0].get("ward_code") if len(ward_rows) == 1 else None
	school.update(
		{
			"canonical_id": f"{province_code}-{ward_code}-{school_code}" if ward_code else None,
			"province_code": province_code,
			"ward_code": ward_code,
		}
	)
	return school


def fact(value: Any, *, state: str | None = None) -> dict[str, Any]:
	availability = state or ("unavailable" if value is None else "available")
	if availability not in AVAILABILITY_STATES:
		raise ValueError("unsupported availability state")
	return {"value": value, "availability": availability}


def as_iso(value: Any) -> str | None:
	if value in (None, ""):
		return None
	if isinstance(value, (date, datetime)):
		return value.isoformat()
	return str(value)
