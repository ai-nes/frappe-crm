import frappe


def execute():
    frappe.db.sql("""
        UPDATE `tabCRM High School` h
        JOIN `tabCRM Province` p ON p.name = h.province
        SET h.province_name = p.province_name,
            h.province_code = p.province_code
        WHERE h.province IS NOT NULL AND h.province != ''
    """)
    frappe.db.commit()
