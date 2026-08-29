"""Backfill enrollment transitions into lifecycle events and retire the table."""

from __future__ import annotations

import frappe

from crm.fcrm.doctype.crm_student.enrollment_transition import _insert_lifecycle_event


def execute():
	has_doctype = frappe.db.exists("DocType", "CRM Enrollment Transition")
	has_table = bool(frappe.db.sql("SHOW TABLES LIKE %s", ("tabCRM Enrollment Transition",)))
	if not has_doctype and not has_table:
		return {"before": 0, "migrated": 0, "after": 0}
	rows = (
		frappe.get_all(
			"CRM Enrollment Transition",
			fields=["name", "student", "from_status", "to_status", "from_date", "log_owner", "source"],
			order_by="from_date asc, name asc",
		)
		if has_doctype
		else frappe.db.sql("select name, student, from_status, to_status, from_date, log_owner, source from `tabCRM Enrollment Transition` order by from_date asc, name asc", as_dict=True)
	)
	for row in rows:
		if frappe.db.sql("select name from `tabCRM Student Lifecycle Event` where evidence_references like %s limit 1", (f'%legacy_enrollment_transition:{row.name}%',)):
			continue
		_insert_lifecycle_event(
			row.student,
			row.from_status,
			row.to_status,
			row.from_date,
			row.log_owner or "Administrator",
			f"legacy_enrollment_transition:{row.name}",
		)
	after = frappe.db.sql("select count(*) from `tabCRM Student Lifecycle Event` where evidence_references like %s", ("%legacy_enrollment_transition:%",))[0][0]
	if after < len(rows):
		frappe.throw(f"Enrollment transition migration incomplete: expected {len(rows)}, found {after}")
	if has_doctype:
		frappe.delete_doc("DocType", "CRM Enrollment Transition", ignore_permissions=True, force=True)
	if frappe.db.sql("SHOW TABLES LIKE %s", ("tabCRM Enrollment Transition",)):
		frappe.db.sql_ddl("DROP TABLE `tabCRM Enrollment Transition`")
	return {"before": len(rows), "migrated": len(rows), "after": after}
