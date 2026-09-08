"""Gán vùng miền cho Tỉnh/TP, chuẩn hoá bản ghi TP.HCM và mã Campus còn thiếu.

Group/Team đọc địa bàn qua ``CRM Team Group.province`` → ``CRM Province.region``
→ ``CRM Region``. Bảng ``CRM Province`` được tạo từ file import địa lý nên cột
``region`` chưa bao giờ được điền, khiến API quản lý team trả ``regionCode``
rỗng. Patch điền theo danh sách 34 tỉnh/thành sau sáp nhập 2025.
"""

import frappe

# province_code -> CRM Region (autoname field:code nên name chính là mã vùng).
REGION_BY_PROVINCE_CODE = {
	# Miền Bắc
	"VN_HA_NOI": "MB",
	"VN_HAI_PHONG": "MB",
	"VN_QUANG_NINH": "MB",
	"VN_BAC_NINH": "MB",
	"VN_HUNG_YEN": "MB",
	"VN_NINH_BINH": "MB",
	"VN_PHU_THO": "MB",
	"VN_THAI_NGUYEN": "MB",
	"VN_LANG_SON": "MB",
	"VN_CAO_BANG": "MB",
	"VN_TUYEN_QUANG": "MB",
	"VN_LAO_CAI": "MB",
	"VN_DIEN_BIEN": "MB",
	"VN_LAI_CHAU": "MB",
	"VN_SON_LA": "MB",
	# Miền Trung (gồm Tây Nguyên)
	"VN_THANH_HOA": "MT",
	"VN_NGHE_AN": "MT",
	"VN_HA_TINH": "MT",
	"VN_QUANG_TRI": "MT",
	"VN_HUE": "MT",
	"VN_DA_NANG": "MT",
	"VN_QUANG_NGAI": "MT",
	"VN_GIA_LAI": "MT",
	"VN_DAK_LAK": "MT",
	"VN_KHANH_HOA": "MT",
	"VN_LAM_DONG": "MT",
	# Miền Nam
	"VN_HO_CHI_MINH": "MN",
	"VN_DONG_NAI": "MN",
	"VN_TAY_NINH": "MN",
	"VN_DONG_THAP": "MN",
	"VN_VINH_LONG": "MN",
	"VN_CAN_THO": "MN",
	"VN_AN_GIANG": "MN",
	"VN_CA_MAU": "MN",
}

# Bản ghi TP.HCM được tạo lệch chuẩn: tên tiếng Anh và mã hành chính "79",
# trong khi 33 tỉnh còn lại dùng tên tiếng Việt và mã "VN_*".
LEGACY_HCMC_NAME = "Ho Chi Minh City"
HCMC_NAME = "Hồ Chí Minh"
HCMC_CODE = "VN_HO_CHI_MINH"

CAMPUS_CODES = {"FPTU Ho Chi Minh Campus": "FPTU-HCM"}


def _normalize_hcmc():
	if not frappe.db.exists("CRM Province", LEGACY_HCMC_NAME):
		return
	if frappe.db.exists("CRM Province", HCMC_NAME):
		# Đã có bản ghi chuẩn, không tự động gộp để tránh mất liên kết.
		frappe.log_error(
			f"Tồn tại đồng thời '{LEGACY_HCMC_NAME}' và '{HCMC_NAME}', cần gộp thủ công.",
			"backfill_province_region",
		)
		return
	# rename_doc cập nhật mọi Link field trỏ tới bản ghi cũ.
	frappe.rename_doc("CRM Province", LEGACY_HCMC_NAME, HCMC_NAME, force=True, show_alert=False)
	frappe.db.set_value(
		"CRM Province",
		HCMC_NAME,
		{"province_name": HCMC_NAME, "province_code": HCMC_CODE},
		update_modified=False,
	)
	# CRM Ward giữ tên tỉnh denormalize trong province_name.
	if frappe.db.has_column("CRM Ward", "province_name"):
		frappe.db.sql(
			"""UPDATE `tabCRM Ward` SET province_name = %s WHERE province = %s""",
			(HCMC_NAME, HCMC_NAME),
		)


def _backfill_regions():
	missing_regions = {
		code
		for code in set(REGION_BY_PROVINCE_CODE.values())
		if not frappe.db.exists("CRM Region", code)
	}
	if missing_regions:
		frappe.log_error(
			f"Thiếu CRM Region: {sorted(missing_regions)}", "backfill_province_region"
		)
	for row in frappe.get_all(
		"CRM Province", fields=["name", "province_code", "region"], limit_page_length=0
	):
		if row.region:
			continue
		region = REGION_BY_PROVINCE_CODE.get(row.province_code)
		if not region or region in missing_regions:
			continue
		frappe.db.set_value("CRM Province", row.name, "region", region, update_modified=False)


def _backfill_campus_codes():
	for campus, code in CAMPUS_CODES.items():
		if not frappe.db.exists("CRM Campus", campus):
			continue
		if frappe.db.get_value("CRM Campus", campus, "campus_code"):
			continue
		frappe.db.set_value("CRM Campus", campus, "campus_code", code, update_modified=False)


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_province")
	frappe.reload_doc("fcrm", "doctype", "crm_region")
	_normalize_hcmc()
	_backfill_regions()
	_backfill_campus_codes()
	frappe.clear_cache()
