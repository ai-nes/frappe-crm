"""Backfill the Student-first profile and admission schema safely.

The model sync changes operational Link fields from ``CRM Lead`` to
``CRM Student``. This patch runs after model sync, resolves converted Lead
references where the canonical Student is known, and leaves unresolved raw
references untouched while recording them for review.
"""

from __future__ import annotations

import json

import frappe

from crm.fcrm.student_reference import canonical_student

LINK_MIGRATIONS = (
	("CRM Admission Application", "student", ("crm_student",), "source_lead"),
	("CRM AI Student Insight", "student", ("contact",), None),
	("CRM Campaign Attribution", "student", (), None),
	("CRM Contact Consent Event", "student", (), None),
	("CRM Marketing Engagement", "student", ("crm_contact",), None),
	("CRM Parent Contact Authority", "student", ("contact",), None),
	("CRM Revenue Recognition", "student", (), None),
	("CRM Student Assessment", "student", ("crm_student",), None),
	("CRM Student Assignment Batch Item", "student", (), None),
	("CRM Student Command Receipt", "target_student", ("target_contact",), None),
	("CRM Student Geography Snapshot", "student", (), None),
	("CRM Student Guardian", "student", ("contact",), None),
	("CRM Student Intake Review", "resulting_student", (), None),
	("CRM Student Ownership Event", "student", (), None),
	("CRM Student Payment", "student", ("crm_student",), None),
	("CRM Student Privacy Request", "student", ("contact",), None),
	("CRM Student Routing Request", "student", (), None),
	("CRM Student SLA Attempt", "student", (), None),
	("CRM Student SLA Delivery", "student", (), None),
	("CRM Student SLA Event", "student", (), None),
	("Task", "student", ("crm_student",), None),
)

STUDENT_FIELD_MIGRATIONS = (
	("student_name", "full_name"),
	("phone", "phone"),
	("email", "email"),
	("other_email", "other_email"),
	("gender", "gender"),
	("date_of_birth", "date_of_birth"),
	("id_number", "id_number"),
	("id_issued_date", "id_issued_date"),
	("id_issued_place", "id_issued_place"),
	("current_grade", "current_grade"),
	("study_stage", "study_stage"),
	("ward", "ward"),
	("admission_year", "admission_year"),
	("high_school", "high_school"),
	("province", "province"),
	("major", "major"),
	("aspiration", "aspiration"),
	("education_program", "education_program"),
	("branch", "branch"),
	("graduation_score", "graduation_score"),
	("transcript_score", "transcript_score"),
	("english_converted_score", "english_converted_score"),
	("total_score", "total_score"),
	("notes", "notes"),
	("alt_name", "parent_name"),
	("alt_phone", "parent_phone"),
	("alt_address", "contact_address"),
	("identity", "student_identity"),
)

CHILD_TABLES = (
	("CRM Student Academic Result", "academic_results"),
	("CRM Student Language Certificate", "language_certificates"),
)

DOCUMENT_TYPE_SEEDS = (
	("PERSONAL_ID", "CCCD / Hộ chiếu", "identity"),
	("BIRTH_CERTIFICATE", "Giấy khai sinh", "identity"),
	("PORTRAIT_PHOTO", "Ảnh chân dung", "photo"),
	("HIGH_SCHOOL_TRANSCRIPT", "Học bạ THPT", "education"),
	("HIGH_SCHOOL_EXAM_RESULT", "Giấy chứng nhận kết quả thi THPT", "education"),
	("HIGH_SCHOOL_GRADUATION", "Bằng / giấy chứng nhận tốt nghiệp THPT", "education"),
	("COLLEGE_TRANSCRIPT", "Bảng điểm cao đẳng", "education"),
	("COLLEGE_GRADUATION", "Bằng / giấy chứng nhận tốt nghiệp cao đẳng", "education"),
	("LANGUAGE_CERTIFICATE", "Chứng chỉ ngoại ngữ", "language"),
	("SCHOLARSHIP_PROOF", "Hồ sơ học bổng", "scholarship"),
	("PRIORITY_PROOF", "Giấy tờ ưu tiên", "special_program"),
	("PROGRAM_SPECIFIC", "Giấy tờ theo chương trình", "special_program"),
)


def execute():
	if not _exists("CRM Lead") or not _exists("CRM Student"):
		return {"status": "skipped", "reason": "student_or_lead_doctype_missing"}

	report = {
		"status": "applied",
		"links_migrated": 0,
		"student_fields_migrated": 0,
		"child_rows_migrated": 0,
		"document_types_seeded": 0,
		"unresolved_links": [],
	}
	_backfill_student_source_links()
	_backfill_student_fields(report)
	_backfill_student_child_rows(report)
	_backfill_links(report)
	_seed_document_types(report)
	if report["unresolved_links"]:
		frappe.log_error(
			message=json.dumps(report["unresolved_links"], ensure_ascii=False, sort_keys=True),
			title="Student-first admission link migration review",
		)
	for doctype in {item[0] for item in LINK_MIGRATIONS} | {"CRM Student"}:
		frappe.clear_cache(doctype=doctype)
	return report


def _exists(doctype: str) -> bool:
	return bool(frappe.db.exists("DocType", doctype))


def _fields(doctype: str) -> set[str]:
	return {field.fieldname for field in frappe.get_meta(doctype).fields}


def _non_empty(value) -> bool:
	return value not in (None, "")


def _backfill_student_source_links():
	student_fields = _fields("CRM Student")
	lead_fields = _fields("CRM Lead")
	if "source_lead" not in student_fields:
		return
	lead_names = set(frappe.get_all("CRM Lead", pluck="name", limit_page_length=0, ignore_permissions=True))
	read_fields = ["name", "source_lead"]
	for fieldname in ("student",):
		if fieldname in student_fields:
			read_fields.append(fieldname)
	for student in frappe.get_all(
		"CRM Student", fields=read_fields, limit_page_length=0, ignore_permissions=True
	):
		if student.get("source_lead"):
			continue
		lead = None
		for candidate in (student.get("student"),):
			if candidate and candidate in lead_names:
				lead = candidate
				break
		if not lead and "converted_student" in lead_fields:
			lead = frappe.db.get_value("CRM Lead", {"converted_student": student.name}, "name")
		if lead and lead in lead_names:
			frappe.db.set_value("CRM Student", student.name, "source_lead", lead, update_modified=False)


def _backfill_student_fields(report: dict):
	student_fields = _fields("CRM Student")
	lead_fields = _fields("CRM Lead")
	student_read_fields = ["name", "source_lead", "student"]
	student_read_fields.extend(
		student_field for _, student_field in STUDENT_FIELD_MIGRATIONS if student_field in student_fields
	)
	lead_read_fields = ["name"]
	lead_read_fields.extend(source for source, _ in STUDENT_FIELD_MIGRATIONS if source in lead_fields)
	for student in frappe.get_all(
		"CRM Student", fields=student_read_fields, limit_page_length=0, ignore_permissions=True
	):
		lead_name = student.get("source_lead") or student.get("student")
		if not lead_name or not frappe.db.exists("CRM Lead", lead_name):
			continue
		lead = frappe.db.get_value("CRM Lead", lead_name, lead_read_fields, as_dict=True) or {}
		updates = {}
		for lead_field, student_field in STUDENT_FIELD_MIGRATIONS:
			if lead_field not in lead_fields or student_field not in student_fields:
				continue
			if _non_empty(student.get(student_field)) or not _non_empty(lead.get(lead_field)):
				continue
			updates[student_field] = lead.get(lead_field)
		if updates:
			frappe.db.set_value("CRM Student", student.name, updates, update_modified=False)
			report["student_fields_migrated"] += len(updates)


def _backfill_student_child_rows(report: dict):
	student_fields = _fields("CRM Student")
	for child_doctype, parentfield in CHILD_TABLES:
		if not _exists(child_doctype) or parentfield not in student_fields:
			continue
		child_fields = _fields(child_doctype)
		for student in frappe.get_all(
			"CRM Student",
			fields=["name", "source_lead", "student"],
			limit_page_length=0,
			ignore_permissions=True,
		):
			lead_name = student.get("source_lead") or student.get("student")
			if not lead_name or not frappe.db.exists("CRM Lead", lead_name):
				continue
			if frappe.db.exists(child_doctype, {"parent": student.name, "parenttype": "CRM Student"}):
				continue
			rows = frappe.get_all(
				child_doctype,
				filters={"parent": lead_name, "parenttype": "CRM Lead"},
				fields=[
					fieldname
					for fieldname in child_fields
					if fieldname not in {"name", "parent", "parenttype", "parentfield"}
				],
				order_by="idx asc",
				limit_page_length=0,
				ignore_permissions=True,
			)
			for row in rows:
				data = {fieldname: row.get(fieldname) for fieldname in row if fieldname in child_fields}
				data.update(
					{
						"doctype": child_doctype,
						"parent": student.name,
						"parenttype": "CRM Student",
						"parentfield": parentfield,
					}
				)
				frappe.get_doc(data).insert(ignore_permissions=True)
				report["child_rows_migrated"] += 1


def _backfill_links(report: dict):
	for doctype, fieldname, fallback_fields, source_field in LINK_MIGRATIONS:
		if not _exists(doctype):
			continue
		fields = _fields(doctype)
		if fieldname not in fields:
			continue
		read_fields = ["name", fieldname]
		read_fields.extend(field for field in fallback_fields if field in fields)
		if source_field and source_field in fields:
			read_fields.append(source_field)
		for row in frappe.get_all(doctype, fields=read_fields, limit_page_length=0, ignore_permissions=True):
			value = row.get(fieldname)
			student = canonical_student(value) if value else None
			if not student:
				for fallback in fallback_fields:
					student = canonical_student(row.get(fallback))
					if student:
						break
			if not student:
				if value:
					report["unresolved_links"].append(
						{"doctype": doctype, "name": row.name, "fieldname": fieldname, "value": value}
					)
				continue
			updates = {}
			if value != student:
				updates[fieldname] = student
				if source_field and source_field in fields and not row.get(source_field):
					updates[source_field] = value
			elif not value:
				updates[fieldname] = student
			if updates:
				frappe.db.set_value(doctype, row.name, updates, update_modified=False)
				report["links_migrated"] += 1


def _seed_document_types(report: dict):
	if not _exists("CRM Document Type"):
		return
	for code, label, category in DOCUMENT_TYPE_SEEDS:
		if frappe.db.exists("CRM Document Type", {"code": code}):
			continue
		frappe.get_doc(
			{
				"doctype": "CRM Document Type",
				"code": code,
				"label": label,
				"category": category,
				"status": "Active",
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		report["document_types_seeded"] += 1
