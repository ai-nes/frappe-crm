"""Seed the controlled values required by the Lead CSV contract."""

from __future__ import annotations

import re
import unicodedata

import frappe

PROVINCES = (
	("An Giang", "province"),
	("Bắc Ninh", "province"),
	("Cao Bằng", "province"),
	("Cà Mau", "province"),
	("Đắk Lắk", "province"),
	("Điện Biên", "province"),
	("Đồng Nai", "province"),
	("Đồng Tháp", "province"),
	("Gia Lai", "province"),
	("Hà Tĩnh", "province"),
	("Hưng Yên", "province"),
	("Khánh Hòa", "province"),
	("Lai Châu", "province"),
	("Lạng Sơn", "province"),
	("Lào Cai", "province"),
	("Lâm Đồng", "province"),
	("Nghệ An", "province"),
	("Ninh Bình", "province"),
	("Phú Thọ", "province"),
	("Quảng Ninh", "province"),
	("Quảng Ngãi", "province"),
	("Quảng Trị", "province"),
	("Sơn La", "province"),
	("Tây Ninh", "province"),
	("Thái Nguyên", "province"),
	("Thanh Hóa", "province"),
	("Tuyên Quang", "province"),
	("Vĩnh Long", "province"),
	("Hà Nội", "city"),
	("Hải Phòng", "city"),
	("Huế", "city"),
	("Đà Nẵng", "city"),
	("Hồ Chí Minh", "city"),
	("Cần Thơ", "city"),
)

CAMPUSES = (
	("FPTU Hanoi Campus", "FPTU-HN", "Hà Nội"),
	("FPTU Ho Chi Minh Campus", "FPTU-HCM", "Hồ Chí Minh"),
	("FPTU Da Nang Campus", "FPTU-DN", "Đà Nẵng"),
	("FPTU Can Tho Campus", "FPTU-CT", "Cần Thơ"),
	("FPTU Quy Nhon Campus", "FPTU-QN", "Gia Lai"),
)


def _normalized(value: str) -> str:
	value = (value or "").replace("đ", "d").replace("Đ", "D")
	value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
	value = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
	value = re.sub(r"^(tp|thanh_pho|tinh)_", "", value)
	value = re.sub(r"_(city|province)$", "", value)
	return value


def _province_aliases(value: str) -> set[str]:
	key = _normalized(value)
	aliases = {key}
	if key == "dong_nai":
		aliases.add("tp_dong_nai")
	if key == "ho_chi_minh":
		aliases.update({"ho_chi_minh_city", "tp_ho_chi_minh"})
	return aliases


def _find_province(name: str) -> str | None:
	targets = _province_aliases(name)
	for row in frappe.get_all("CRM Province", fields=["name", "province_name"], limit_page_length=0):
		if _normalized(row.province_name) in targets or _normalized(row.name) in targets:
			return row.name
	return None


def _province_code(name: str) -> str:
	code = _normalized(name).upper()
	return f"VN_{code}"


def _ensure_provinces() -> dict[str, str]:
	resolved = {}
	for province_name, city_type in PROVINCES:
		existing = _find_province(province_name)
		if existing:
			resolved[province_name] = existing
			continue
		code = _province_code(province_name)
		if frappe.db.exists("CRM Province", code):
			code = f"{code}_NEW"
		resolved[province_name] = (
			frappe.get_doc(
				{
					"doctype": "CRM Province",
					"province_code": code,
					"province_name": province_name,
					"city_type": "Centrally Controlled City" if city_type == "city" else "Province",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	return resolved


def _ensure_campuses(provinces: dict[str, str]) -> None:
	for campus_name, campus_code, province_name in CAMPUSES:
		if frappe.db.exists("CRM Campus", campus_name):
			continue
		province = provinces.get(province_name) or _find_province(province_name)
		frappe.get_doc(
			{
				"doctype": "CRM Campus",
				"campus_name": campus_name,
				"campus_code": campus_code,
				"province": province,
				"is_default": 0,
			}
		).insert(ignore_permissions=True)


def _ensure_source() -> None:
	if frappe.db.exists("CRM Lead Source", "Promoter"):
		return
	frappe.get_doc(
		{
			"doctype": "CRM Lead Source",
			"source_name": "Promoter",
			"channel_family": "Referral",
			"is_digital": 0,
		}
	).insert(ignore_permissions=True)


def _ensure_follow_up_status() -> None:
	if frappe.db.exists("CRM Enrollment Status", "FOLLOW_UP"):
		return
	frappe.get_doc(
		{
			"doctype": "CRM Enrollment Status",
			"code": "FOLLOW_UP",
			"display_name": "Hẹn liên hệ sau",
			"enabled": 1,
			"sort_order": 25,
			"stage_category": "open",
			"lifecycle_stage": "Lead",
			"stage_order": 2,
		}
	).insert(ignore_permissions=True)


def execute():
	previous_flag = frappe.flags.get("crm_governance_additive")
	frappe.flags.crm_governance_additive = True
	try:
		provinces = _ensure_provinces()
		_ensure_campuses(provinces)
		_ensure_source()
		_ensure_follow_up_status()
		frappe.db.commit()
	finally:
		frappe.flags.crm_governance_additive = previous_flag
