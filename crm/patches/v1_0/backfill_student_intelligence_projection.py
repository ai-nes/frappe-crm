"""Backfill Student-only NBA projection fields from converted Leads."""

from __future__ import annotations

import frappe


FIELDS = (
	"assessment_status",
	"assessment_revision",
	"interest_level",
	"fit_level",
	"primary_barrier",
	"sla_evidence_state",
	"sla_evidence_observed_at",
	"privacy_status",
)


def execute():
	student_fields = {field.fieldname for field in frappe.get_meta("CRM Student").fields}
	lead_fields = {field.fieldname for field in frappe.get_meta("CRM Lead").fields}
	fields = [field for field in FIELDS if field in student_fields and field in lead_fields]
	if not fields:
		return
	for lead in frappe.get_all(
		"CRM Lead",
		fields=["name", "student", "converted_student", *fields],
		limit_page_length=0,
		ignore_permissions=True,
	):
		student = lead.get("converted_student") or lead.get("student")
		if not student or not frappe.db.exists("CRM Student", student):
			continue
		values = {field: lead.get(field) for field in fields if lead.get(field) not in (None, "")}
		if values:
			frappe.db.set_value("CRM Student", student, values, update_modified=False)
