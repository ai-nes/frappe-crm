import frappe


VALUE_MAPS = {
	"Enrollment Student": {
		"enrollment_status": {
			"Chờ xác nhận": "Pending Confirmation",
			"Đã nhập học": "Enrolled",
			"Bảo lưu": "Deferred",
			"Thôi học": "Withdrawn",
		}
	},
	"CRM Province": {
		"city_type": {
			"Thành phố trực thuộc TW": "Centrally Controlled City",
			"Tỉnh": "Province",
		}
	},
	"CRM Ward": {
		"ward_type": {
			"Phường/Xã": "Ward",
			"Phường": "Ward",
			"Xã": "Commune",
			"Thị trấn": "Township",
		}
	},
}


def execute():
	for doctype, fields in VALUE_MAPS.items():
		if not frappe.db.table_exists(doctype):
			continue

		for fieldname, values in fields.items():
			if not frappe.db.has_column(doctype, fieldname):
				continue

			for old_value, new_value in values.items():
				frappe.db.set_value(
					doctype,
					{fieldname: old_value},
					fieldname,
					new_value,
					update_modified=False,
				)
