import frappe


def execute():
	frappe.db.set_single_value("System Settings", "language", "vi")

	users = frappe.db.get_all(
		"User",
		filters={"enabled": 1},
		fields=["name", "language"],
	)
	for user in users:
		if not user.language:
			frappe.db.set_value("User", user.name, "language", "vi")

	frappe.db.commit()

