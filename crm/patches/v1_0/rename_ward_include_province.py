import frappe


def execute():
	_drop_ward_code_unique_indexes()

	wards = frappe.get_all(
		"CRM Ward",
		fields=["name", "ward_code", "province"],
		order_by="name asc",
	)

	for ward in wards:
		if not ward.ward_code or not ward.province:
			continue

		expected = f"{ward.ward_code} - {ward.province}"
		if ward.name == expected:
			continue

		if frappe.db.exists("CRM Ward", expected):
			frappe.log_error(
				title="rename_ward_include_province: skip",
				message=f"Target already exists: {ward.name!r} -> {expected!r}",
			)
			continue

		try:
			frappe.rename_doc(
				"CRM Ward",
				ward.name,
				expected,
				ignore_permissions=True,
			)
		except Exception as e:
			frappe.log_error(
				title="rename_ward_include_province: failed",
				message=f"{ward.name!r} -> {expected!r}\n{e}",
			)

	frappe.db.commit()


def _drop_ward_code_unique_indexes():
	indexes = frappe.db.sql(
		"""
		SHOW INDEX FROM `tabCRM Ward`
		WHERE Column_name = 'ward_code' AND Non_unique = 0
		""",
		as_dict=True,
	)

	for index in indexes:
		frappe.db.sql(f"ALTER TABLE `tabCRM Ward` DROP INDEX `{index.Key_name}`")
