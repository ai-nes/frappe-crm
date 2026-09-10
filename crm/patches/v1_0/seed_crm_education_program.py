import frappe


PROGRAMS = [
	("THPT thường",        "Chính quy"),
	("THPT chuyên",        "Chính quy"),
	("GDTX",               "GDTX"),
	("Song ngữ",           "Chính quy"),
	("Quốc tế",            "Quốc tế"),
	("Cao đẳng liên thông", "Liên thông"),
]


def execute():
	existing = set(frappe.db.get_all("CRM Education Program", pluck="name"))
	for program_name, program_type in PROGRAMS:
		if program_name not in existing:
			frappe.get_doc({
				"doctype": "CRM Education Program",
				"program_name": program_name,
				"program_type": program_type,
			}).insert(ignore_permissions=True, ignore_if_duplicate=True)

	frappe.db.commit()
	frappe.clear_cache()
