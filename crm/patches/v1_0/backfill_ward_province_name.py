import frappe


def execute():
	frappe.db.sql("""
		UPDATE `tabCRM Ward` w
		JOIN `tabCRM Province` p ON p.name = w.province
		SET w.province_name = p.province_name
		WHERE w.province IS NOT NULL AND w.province != ''
	""")
	frappe.db.commit()
