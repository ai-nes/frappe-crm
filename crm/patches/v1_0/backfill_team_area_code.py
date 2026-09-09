"""Suy ``CRM Team.area_code`` từ tên Team để mã Team sinh được ngay.

``team_code`` = ``{group_code}-{area_code}-{loại}``. Tên Team hiện có đã chứa
khu vực phụ trách ("Đội Tư vấn Biên Hòa - Đồng Nai"), nên lấy đoạn giữa làm mã
khu vực. Chỉ chạm Team thuộc Group đã gắn tỉnh — Team trong group placeholder
không sinh được mã nên để trống, tránh đoán từ những cái tên không theo quy ước.
"""

import re
import unicodedata

import frappe

TEAM_NAME_PREFIXES = ("Đội Tư vấn", "Đội tư vấn", "Đội", "Team", "Nhóm")


D_STROKE = str.maketrans({"Đ": "D", "đ": "d"})


def _segment(value):
	# NFKD không tách được Đ/đ nên phải map tay, nếu không "Thủ Đức" ra "THUUC".
	folded = str(value or "").translate(D_STROKE)
	folded = unicodedata.normalize("NFKD", folded).encode("ascii", "ignore").decode()
	return re.sub(r"[^A-Z0-9]", "", folded.upper())


def _area_from_name(team_name):
	# "Đội Tư vấn Biên Hòa - Đồng Nai" -> "Biên Hòa": bỏ đuôi tỉnh sau " - ".
	head = str(team_name or "").split(" - ")[0].strip()
	for prefix in TEAM_NAME_PREFIXES:
		if head.startswith(prefix):
			head = head[len(prefix) :].strip()
			break
	return _segment(head)


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_team")
	if not frappe.db.has_column("CRM Team", "area_code"):
		return

	groups_with_province = {
		row.name
		for row in frappe.get_all(
			"CRM Team Group", filters={"province": ["is", "set"]}, fields=["name"], limit_page_length=0
		)
	}
	taken = {}
	teams = frappe.get_all(
		"CRM Team", fields=["name", "team_name", "group", "area_code"], limit_page_length=0
	)
	for row in teams:
		if row.area_code:
			taken.setdefault(row.group, set()).add(row.area_code)
	for row in teams:
		if row.area_code or row.group not in groups_with_province:
			continue
		area = _area_from_name(row.team_name)
		if not area or area in taken.setdefault(row.group, set()):
			continue
		frappe.db.set_value("CRM Team", row.name, "area_code", area, update_modified=False)
		taken[row.group].add(area)
	frappe.clear_cache()
