import frappe

REGIONS = [
	{"region_name": "Miền Bắc", "region_code": "MB"},
	{"region_name": "Miền Trung", "region_code": "MT"},
	{"region_name": "Miền Nam", "region_code": "MN"},
]

NORTH_PROVINCES = [
	"Hà Nội", "Hải Phòng", "Quảng Ninh", "Bắc Ninh", "Bắc Giang", "Hà Nam", "Hải Dương",
	"Hưng Yên", "Nam Định", "Ninh Bình", "Thái Bình", "Vĩnh Phúc", "Phú Thọ", "Thái Nguyên",
	"Tuyên Quang", "Hà Giang", "Cao Bằng", "Bắc Kạn", "Lạng Sơn", "Lào Cai", "Yên Bái",
	"Điện Biên", "Lai Châu", "Sơn La", "Hòa Bình"
]

CENTRAL_PROVINCES = [
	"Đà Nẵng", "Thừa Thiên Huế", "Quảng Trị", "Quảng Bình", "Hà Tĩnh", "Nghệ An", "Thanh Hóa",
	"Quảng Nam", "Quảng Ngãi", "Bình Định", "Phú Yên", "Khánh Hòa", "Ninh Thuận", "Bình Thuận",
	"Kon Tum", "Gia Lai", "Đắk Lắk", "Đắk Nông", "Lâm Đồng"
]

SOUTH_PROVINCES = [
	"TP. Hồ Chí Minh", "Thành phố Hồ Chí Minh", "Bà Rịa - Vũng Tàu", "Bình Dương", "Bình Phước",
	"Đồng Nai", "Tây Ninh", "Cần Thơ", "An Giang", "Bạc Liêu", "Bến Tre", "Cà Mau",
	"Đồng Tháp", "Hậu Giang", "Kiên Giang", "Long An", "Sóc Trăng", "Tiền Giang", "Trà Vinh", "Vĩnh Long"
]

LEAD_SOURCE_CONFIG = {
	"Facebook": {"is_digital": 1, "channel_family": "Social"},
	"TikTok": {"is_digital": 1, "channel_family": "Social"},
	"Google": {"is_digital": 1, "channel_family": "Search"},
	"Website": {"is_digital": 1, "channel_family": "Direct/Website"},
	"Zalo": {"is_digital": 1, "channel_family": "Social"},
	"Referral": {"is_digital": 0, "channel_family": "Referral"},
	"Event": {"is_digital": 0, "channel_family": "Event/Offline"},
}


def execute():
	# 1. Seed CRM Region
	for reg in REGIONS:
		if not frappe.db.exists("CRM Region", reg["region_name"]):
			frappe.get_doc({
				"doctype": "CRM Region",
				"region_name": reg["region_name"],
				"region_code": reg["region_code"]
			}).insert(ignore_permissions=True)

	# 2. Update CRM Province region
	for name in NORTH_PROVINCES:
		if frappe.db.exists("CRM Province", name):
			frappe.db.set_value("CRM Province", name, "region", "Miền Bắc", update_modified=False)

	for name in CENTRAL_PROVINCES:
		if frappe.db.exists("CRM Province", name):
			frappe.db.set_value("CRM Province", name, "region", "Miền Trung", update_modified=False)

	for name in SOUTH_PROVINCES:
		if frappe.db.exists("CRM Province", name):
			frappe.db.set_value("CRM Province", name, "region", "Miền Nam", update_modified=False)

	# 3. Update Lead Sources
	for source_name, config in LEAD_SOURCE_CONFIG.items():
		if frappe.db.exists("CRM Lead Source", source_name):
			frappe.db.set_value(
				"CRM Lead Source",
				source_name,
				{
					"is_digital": config["is_digital"],
					"channel_family": config["channel_family"]
				},
				update_modified=False
			)

	frappe.db.commit()
