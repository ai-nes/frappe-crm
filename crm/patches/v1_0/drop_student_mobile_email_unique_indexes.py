import frappe


def execute():
	for fieldname in ("mobile_no", "email"):
		_drop_unique_indexes("CRM Lead", fieldname)

	frappe.db.commit()


def _drop_unique_indexes(doctype, fieldname):
	indexes = frappe.db.sql(
		f"""
		SHOW INDEX FROM `tab{doctype}`
		WHERE Column_name = %s AND Non_unique = 0
		""",
		(fieldname,),
		as_dict=True,
	)

	for index in indexes:
		frappe.db.sql(f"ALTER TABLE `tab{doctype}` DROP INDEX `{index.Key_name}`")
