import frappe


def execute():
	if not frappe.db.has_column("CRM Province", "city_number"):
		return

	frappe.db.sql("""
		UPDATE `tabCRM Province`
		SET province_code = city_number
		WHERE (province_code IS NULL OR province_code = '')
		  AND city_number IS NOT NULL
		  AND city_number != ''
	""")

	frappe.db.sql("""
		UPDATE `tabCRM Province`
		SET name = province_code
		WHERE province_code != ''
		  AND name != province_code
	""")

	frappe.db.commit()
