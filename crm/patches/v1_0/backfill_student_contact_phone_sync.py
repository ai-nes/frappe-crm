import frappe


def execute():
	student_columns = {row[0] for row in frappe.db.sql("SHOW COLUMNS FROM `tabCRM Student`")}
	if "mobile_no" in student_columns:
		frappe.db.sql("""
			UPDATE `tabCRM Contact` contact
			JOIN `tabCRM Student` student ON student.name = contact.student
			SET contact.phone = student.mobile_no
			WHERE contact.student IS NOT NULL
			  AND contact.student != ''
			  AND (contact.phone IS NULL OR contact.phone = '')
			  AND student.mobile_no IS NOT NULL
			  AND student.mobile_no != ''
		""")

	frappe.db.sql("""
		UPDATE `tabCRM Student` student
		JOIN `tabCRM Contact` contact ON contact.student = student.name
		SET student.phone = contact.phone
		WHERE contact.student IS NOT NULL
		  AND contact.student != ''
		  AND contact.phone IS NOT NULL
		  AND contact.phone != ''
		  AND (student.phone IS NULL OR student.phone = '')
	""")

	frappe.db.commit()
