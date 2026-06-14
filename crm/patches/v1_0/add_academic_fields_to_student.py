import frappe


ACADEMIC_FIELDS = (
	"cohort_start_year",
	"education_program",
	"graduation_score",
	"transcript_score",
	"cohort_end_year",
	"admission_method",
	"english_converted_score",
	"total_score",
)


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_student", force=True)
	frappe.reload_doc("fcrm", "doctype", "crm_student_academic_result", force=True)
	frappe.reload_doc("fcrm", "doctype", "crm_student_language_certificate", force=True)

	_copy_contact_academic_fields_to_student()
	_copy_contact_child_rows_to_student("CRM Student Academic Result")
	_copy_contact_child_rows_to_student("CRM Student Language Certificate")
	_drop_student_mobile_no_if_exists()


def _copy_contact_academic_fields_to_student():
	for contact in frappe.get_all(
		"CRM Contact",
		filters={"student": ["!=", ""]},
		fields=["name", "student", *ACADEMIC_FIELDS],
	):
		updates = {}
		for fieldname in ACADEMIC_FIELDS:
			value = contact.get(fieldname)
			if value not in (None, ""):
				updates[fieldname] = value
		if updates:
			frappe.db.set_value("CRM Student", contact.student, updates, update_modified=False)


def _copy_contact_child_rows_to_student(child_doctype):
	for contact in frappe.get_all("CRM Contact", filters={"student": ["!=", ""]}, fields=["name", "student"]):
		existing = frappe.db.exists(child_doctype, {"parenttype": "CRM Student", "parent": contact.student})
		if existing:
			continue

		source_rows = frappe.get_all(
			child_doctype,
			filters={"parenttype": "CRM Contact", "parent": contact.name},
			fields=["*"],
			order_by="idx asc",
		)
		for row in source_rows:
			data = dict(row)
			for fieldname in ("name", "creation", "modified", "modified_by", "owner"):
				data.pop(fieldname, None)
			data.update({
				"doctype": child_doctype,
				"parenttype": "CRM Student",
				"parent": contact.student,
				"parentfield": _student_parentfield(child_doctype),
			})
			frappe.get_doc(data).insert(ignore_permissions=True)


def _student_parentfield(child_doctype):
	if child_doctype == "CRM Student Academic Result":
		return "academic_results"
	return "language_certificates"


def _drop_student_mobile_no_if_exists():
	existing = {row[0] for row in frappe.db.sql("SHOW COLUMNS FROM `tabCRM Student`")}
	if "mobile_no" in existing:
		frappe.db.commit()
		frappe.db.sql("ALTER TABLE `tabCRM Student` DROP COLUMN `mobile_no`")

	frappe.clear_cache(doctype="CRM Student")
