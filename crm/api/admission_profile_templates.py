"""Read APIs for the admission method, offering and profile template catalog."""

from __future__ import annotations

from typing import Any

import frappe

SUPPORTED_ADMISSION_METHOD_CODES = ("THPT_SCORE", "DIRECT_ADMISSION")


def _as_bool(value: Any) -> bool:
	return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _requirement(row, document_types: dict[str, Any]) -> dict[str, Any]:
	document_type = str(row.get("document_type") or "").strip()
	descriptor = document_types.get(document_type, frappe._dict())
	return {
		"sectionCode": row.get("section_code") or "general",
		"documentType": document_type,
		"documentCode": descriptor.get("code") or document_type,
		"documentLabel": descriptor.get("label") or document_type,
		"category": descriptor.get("category"),
		"description": descriptor.get("description"),
		"requirementGroup": row.get("requirement_group") or f"document:{document_type}",
		"requirementMode": str(row.get("requirement_mode") or "ALL").upper(),
		"isRequired": _as_bool(row.get("is_required")),
		"minimumRequired": int(row.get("min_required") or 1),
		"quantity": int(row.get("quantity") or 1),
		"orderDisplay": int(row.get("order_display") or 0),
		"conditionKey": row.get("condition_key"),
		"instruction": row.get("instruction"),
	}


def _offering_label(row, method_labels: dict[str, str], year_labels: dict[str, str]) -> str:
	year = year_labels.get(row.admission_year) or row.admission_year
	method = method_labels.get(row.admission_method) or row.admission_method
	parts = [year, row.campus, row.major, method]
	return " · ".join(str(part) for part in parts if part)


@frappe.whitelist()
def get_admission_profile_catalog(admission_year: str | None = None) -> dict[str, Any]:
	"""Return the active catalog needed to create a Student admission profile."""
	method_rows = frappe.get_list(
		"CRM Admission Method",
		filters={
			"enabled": 1,
			"code": ["in", list(SUPPORTED_ADMISSION_METHOD_CODES)],
		},
		fields=["name", "code", "display_name", "description", "sort_order", "enabled"],
		order_by="sort_order asc, display_name asc",
		limit_page_length=0,
	)
	methods = [
		{
			"id": row.name,
			"code": row.code or row.name,
			"name": row.display_name or row.name,
			"description": row.description,
			"sortOrder": int(row.sort_order or 0),
		}
		for row in method_rows
		if row.code in SUPPORTED_ADMISSION_METHOD_CODES
	]
	method_labels = {item["id"]: item["name"] for item in methods}
	method_labels.update({item["code"]: item["name"] for item in methods})

	year_filters = {"is_active": 1}
	if admission_year:
		year_filters["name"] = admission_year
	year_rows = frappe.get_list(
		"CRM Admission Year",
		filters=year_filters,
		fields=["name", "year_name", "is_active", "start_date", "end_date"],
		order_by="year_name desc",
		limit_page_length=0,
	)
	years = [
		{
			"id": row.name,
			"name": row.year_name or row.name,
			"isActive": _as_bool(row.is_active),
			"startDate": row.start_date,
			"endDate": row.end_date,
		}
		for row in year_rows
	]
	year_labels = {item["id"]: item["name"] for item in years}

	document_rows = frappe.get_list(
		"CRM Document Type",
		filters={"status": "Active", "is_active": 1},
		fields=["name", "code", "label", "category", "description"],
		order_by="label asc",
		limit_page_length=0,
	)
	document_types = {row.name: row for row in document_rows}

	template_rows = frappe.get_list(
		"CRM Admission Profile Template",
		filters={"status": "Active", "profile_type": "academic_admission"},
		fields=[
			"name",
			"template_code",
			"template_name",
			"profile_type",
			"status",
			"version",
			"education_program",
			"admission_method",
			"description",
		],
		order_by="template_code asc, version desc",
		limit_page_length=0,
	)
	templates = []
	for row in template_rows:
		template_doc = frappe.get_doc("CRM Admission Profile Template", row.name)
		templates.append(
			{
				"id": row.name,
				"code": row.template_code,
				"name": row.template_name,
				"profileType": row.profile_type,
				"status": row.status,
				"version": int(row.version or 1),
				"educationProgram": row.education_program,
				"admissionMethod": row.admission_method,
				"description": row.description,
				"requirements": [
					_requirement(requirement, document_types)
					for requirement in template_doc.get("document_types") or []
				],
			}
		)

	offering_filters = {"status": "Active"}
	if admission_year:
		offering_filters["admission_year"] = admission_year
	offering_rows = frappe.get_list(
		"CRM Admission Offering",
		filters=offering_filters,
		fields=[
			"name",
			"offering_key",
			"admission_year",
			"campus",
			"major",
			"admission_method",
			"quota",
			"effective_from",
			"effective_until",
			"status",
		],
		order_by="admission_year desc, effective_from desc, name asc",
		limit_page_length=0,
	)
	offerings = [
		{
			"id": row.name,
			"offeringKey": row.offering_key,
			"admissionYear": row.admission_year,
			"admissionYearName": year_labels.get(row.admission_year) or row.admission_year,
			"campus": row.campus,
			"major": row.major,
			"admissionMethod": row.admission_method,
			"admissionMethodName": method_labels.get(row.admission_method) or row.admission_method,
			"quota": int(row.quota or 0),
			"effectiveFrom": row.effective_from,
			"effectiveUntil": row.effective_until,
			"status": row.status,
			"label": _offering_label(row, method_labels, year_labels),
		}
		for row in offering_rows
	]

	return {
		"methods": methods,
		"years": years,
		"offerings": offerings,
		"documentTypes": [
			{
				"id": row.name,
				"code": row.code,
				"name": row.label,
				"category": row.category,
				"description": row.description,
			}
			for row in document_rows
		],
		"templates": templates,
	}
