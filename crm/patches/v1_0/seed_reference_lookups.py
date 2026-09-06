"""Migrate and seed the flat controlled-vocabulary lookups."""

import re
import unicodedata

import frappe

from crm.fcrm.reference_catalog import REFERENCE_CATALOG


LEGACY_CATEGORY_DOCTYPES = {
	"lost_reason": "CRM Lost Reason",
	"campaign_type": "CRM Campaign Type",
	"intent_type": "CRM Intent Type",
	"interaction_type": "CRM Interaction Type",
	"school_type": "CRM School Type",
	"school_area": "CRM School Area",
	"stakeholder_role": "CRM Stakeholder Role",
	"activity_type": "CRM School Activity Type",
	"major_group": "CRM Major Group",
	"aspiration": "CRM Aspiration",
	"region": "CRM Region",
	"enrollment_status": "CRM Enrollment Status",
	"admission_method": "CRM Admission Method",
}

LOOKUP_CONSUMERS = {
	"lost_reason": (),
	"campaign_type": (("CRM Campaign", "campaign_type"),),
	"intent_type": (("CRM Intent", "intent_type"), ("CRM Score Signal", "intent_type")),
	"interaction_type": (("CRM Interaction", "interaction_type"), ("CRM Score Signal", "interaction_term")),
	"school_type": (("CRM High School", "school_type"),),
	"school_area": (("CRM High School", "school_area"),),
	"stakeholder_role": (("CRM School Stakeholder", "stakeholder_role"),),
	"activity_type": (("CRM School Activity", "activity_type"),),
	"major_group": (("CRM Major", "major_group"),),
	"aspiration": (("CRM Contact", "aspiration"), ("CRM Student", "aspiration")),
	"region": (
		("CRM Province", "region"),
		("CRM Territory", "region"),
		("CRM Planning Scope", "region"),
	),
	"enrollment_status": (("CRM Contact", "enrollment_status"), ("CRM Student", "enrollment_status")),
	"admission_method": (
		("CRM Student", "admission_method"),
		("CRM Admission Offering", "admission_method"),
		("CRM Admission Application", "admission_method"),
	),
}


def _as_code(value: str) -> str:
	folded = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
	return re.sub(r"[^A-Z0-9]+", "_", folded.upper()).strip("_")


def _column_names(doctype: str) -> set[str]:
	if not frappe.db.table_exists(doctype):
		return set()
	return {row[0] for row in frappe.db.sql(f"SHOW COLUMNS FROM `tab{doctype}`")}


def _legacy_lookup_code(doctype: str, term_name: str) -> str:
	code = _as_code(term_name)
	if frappe.db.exists(doctype, code):
		return code
	return frappe.db.get_value(doctype, {"display_name": term_name}, "name") or code


def _ensure_legacy_lookup(doctype: str, row: dict) -> str:
	code = _legacy_lookup_code(doctype, row.get("term_name") or row.get("name"))
	if frappe.db.exists(doctype, code):
		return code

	values = {
		"doctype": doctype,
		"code": code,
		"display_name": row.get("term_name") or code,
		"sort_order": row.get("sort_order") or 0,
	}
	if "description" in _column_names(doctype) and row.get("description"):
		values["description"] = row["description"]
	if "enabled" in _column_names(doctype):
		values["enabled"] = 1 if row.get("is_active", 1) else 0
	return frappe.get_doc(values).insert(ignore_permissions=True).name


def _rewrite_legacy_term_references() -> None:
	if not frappe.db.table_exists("CRM Term"):
		return

	legacy_rows = frappe.db.get_all(
		"CRM Term",
		fields=["name", "term_name", "category", "sort_order", "description", "is_active"],
		limit_page_length=0,
	)
	for row in legacy_rows:
		category = row.get("category")
		doctype = LEGACY_CATEGORY_DOCTYPES.get(category)
		# lead_status has no successor by design; Contact.lead_status is dropped
		# separately and must never be silently reinterpreted as enrollment_status.
		if not doctype or not frappe.db.exists("DocType", doctype):
			continue
		code = _ensure_legacy_lookup(doctype, row)
		for consumer_doctype, fieldname in LOOKUP_CONSUMERS[category]:
			columns = _column_names(consumer_doctype)
			if fieldname not in columns:
				continue
			for old_value in {row.get("name"), row.get("term_name")} - {None, ""}:
				frappe.db.sql(
					f"UPDATE `tab{consumer_doctype}` SET `{fieldname}` = %s WHERE `{fieldname}` = %s",
					(code, old_value),
				)


def _rewrite_existing_lookup_codes() -> None:
	"""Normalize legacy Select values whose old labels derive directly to codes."""
	for category, consumers in LOOKUP_CONSUMERS.items():
		doctype = LEGACY_CATEGORY_DOCTYPES[category]
		if not frappe.db.exists("DocType", doctype):
			continue
		for consumer_doctype, fieldname in consumers:
			columns = _column_names(consumer_doctype)
			if fieldname not in columns:
				continue
			for row in frappe.db.get_all(
				consumer_doctype, fields=["name", fieldname], limit_page_length=0
			):
				value = row.get(fieldname)
				if not value or frappe.db.exists(doctype, value):
					continue
				code = _as_code(value)
				if code and frappe.db.exists(doctype, code):
					frappe.db.set_value(
						consumer_doctype, row["name"], fieldname, code, update_modified=False
					)


def _insert_if_missing(doctype, code, values):
	if frappe.db.exists(doctype, code):
		return
	frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)


def execute():
	"""Create canonical rows, then rewrite legacy term links to their codes."""
	for doctype, rows in REFERENCE_CATALOG.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		for row in rows:
			_insert_if_missing(doctype, row["code"], dict(row))
	_rewrite_legacy_term_references()
	_rewrite_existing_lookup_codes()

	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()
