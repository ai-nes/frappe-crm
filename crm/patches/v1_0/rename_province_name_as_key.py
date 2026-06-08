"""
Rename CRM Province records from province_code → province_name as the primary key.
frappe.rename_doc automatically updates all Link field references across all doctypes.
"""

import frappe


def execute():
	provinces = frappe.db.get_all(
		"CRM Province",
		fields=["name", "province_name"],
		order_by="name asc",
	)

	for p in provinces:
		old_name = p.name
		new_name = p.province_name

		if old_name == new_name:
			continue

		if frappe.db.exists("CRM Province", new_name):
			# Already renamed in a previous run
			continue

		frappe.rename_doc("CRM Province", old_name, new_name, force=True)

	frappe.db.commit()
