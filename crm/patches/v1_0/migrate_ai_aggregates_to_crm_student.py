"""Move AI-owned aggregates from raw Leads to qualified CRM Students.

The patch is deliberately additive: rows without a converted CRM Student stay
as historical Lead records and are no longer eligible for AI processing.
"""

from __future__ import annotations

import frappe


AI_STUDENT_DOCTYPES = (
	"CRM Interaction",
	"CRM Interaction Evidence",
	"CRM Intent",
	"CRM Score History",
	"CRM Student Analysis Run",
	"CRM NBA Evaluation",
	"CRM Action Item",
	"CRM Student Revision Journal",
	"CRM Student Command Receipt",
	"CRM Student Decision Event",
	"CRM Student Assessment",
	"CRM Student Engagement Event",
	"CRM Student Outcome",
	"CRM Student Lifecycle Event",
	"CRM Marketing Engagement",
)

STUDENT_INTELLIGENCE_FIELDS = (
	"latest_score",
	"assessment_status",
	"assessment_revision",
	"interest_level",
	"fit_level",
	"primary_barrier",
	"sla_evidence_state",
	"sla_evidence_observed_at",
	"student_context_revision",
	"score_input_revision",
	"applied_score_input_revision",
	"applied_policy_revision",
	"cohort_start_year",
	"cohort_end_year",
	"graduation_score",
	"transcript_score",
	"english_converted_score",
	"total_score",
)


def execute():
	if not _exists("CRM Lead") or not _exists("CRM Student"):
		return
	_copy_intelligence_fields()
	for doctype in AI_STUDENT_DOCTYPES:
		_move_child_student_scope(doctype)
	_move_recommendation_scope()
	_move_agent_event_scope()
	for doctype in AI_STUDENT_DOCTYPES:
		frappe.clear_cache(doctype=doctype)
	frappe.clear_cache(doctype="CRM Student")


def _exists(doctype: str) -> bool:
	return bool(frappe.db.exists("DocType", doctype))


def _fields(doctype: str) -> set[str]:
	return {field.fieldname for field in frappe.get_meta(doctype).fields}


def _lead_student(lead) -> str | None:
	return lead.get("converted_student") or lead.get("student")


def _copy_intelligence_fields():
	student_fields = _fields("CRM Student")
	lead_fields = _fields("CRM Lead")
	common = [field for field in STUDENT_INTELLIGENCE_FIELDS if field in student_fields and field in lead_fields]
	if not common:
		return
	for lead in frappe.get_all(
		"CRM Lead",
		fields=["name", "student", "converted_student", *common],
		limit_page_length=0,
		ignore_permissions=True,
	):
		student = _lead_student(lead)
		if not student or not frappe.db.exists("CRM Student", student):
			continue
		updates = {field: lead.get(field) for field in common if lead.get(field) not in (None, "")}
		if updates:
			frappe.db.set_value("CRM Student", student, updates, update_modified=False)


def _move_child_student_scope(doctype: str):
	if not _exists(doctype):
		return
	fields = _fields(doctype)
	if "student" not in fields:
		return
	canonical_field = "crm_student" if "crm_student" in fields else "crm_contact" if "crm_contact" in fields else None
	rows = frappe.get_all(
		doctype,
		fields=["name", "student", *([canonical_field] if canonical_field else [])],
		limit_page_length=0,
		ignore_permissions=True,
	)
	for row in rows:
		candidate = row.get(canonical_field) if canonical_field else None
		if not candidate:
			candidate = _lead_student(
				frappe.db.get_value("CRM Lead", row.get("student"), ["student", "converted_student"], as_dict=True)
				or {}
			)
		if candidate and frappe.db.exists("CRM Student", candidate):
			updates = {"student": candidate}
			if "crm_student" in fields:
				updates["crm_student"] = candidate
			frappe.db.set_value(doctype, row.name, updates, update_modified=False)


def _move_recommendation_scope():
	if not _exists("CRM Recommendation"):
		return
	for row in frappe.get_all(
		"CRM Recommendation",
		filters={"target_type": "CRM Lead"},
		fields=["name", "target_id"],
		limit_page_length=0,
		ignore_permissions=True,
	):
		student = _lead_student(
			frappe.db.get_value("CRM Lead", row.target_id, ["student", "converted_student"], as_dict=True)
			or {}
		)
		if student and frappe.db.exists("CRM Student", student):
			frappe.db.set_value(
				"CRM Recommendation", row.name, {"target_type": "CRM Student", "target_id": student}, update_modified=False
			)


def _move_agent_event_scope():
	if not _exists("CRM Agent Event"):
		return
	for row in frappe.get_all(
		"CRM Agent Event",
		filters={"aggregate_doctype": "CRM Lead"},
		fields=["name", "aggregate_name"],
		limit_page_length=0,
		ignore_permissions=True,
	):
		student = _lead_student(
			frappe.db.get_value("CRM Lead", row.aggregate_name, ["student", "converted_student"], as_dict=True)
			or {}
		)
		if student and frappe.db.exists("CRM Student", student):
			frappe.db.set_value(
				"CRM Agent Event", row.name,
				{"aggregate_doctype": "CRM Student", "aggregate_name": student},
				update_modified=False,
			)
