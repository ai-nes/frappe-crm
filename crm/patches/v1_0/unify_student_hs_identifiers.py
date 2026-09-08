"""Unify applicant Lead/Student identifiers on the public ``HS-...`` code.

The pre-cutover local data could contain one legacy Contact-shaped ``CRM
Student`` and one converted ``CRM Student`` for the same Lead.  The converted
row is authoritative because it carries ``source_lead``/``lead_code`` and is
the target of the conversion junction.  This patch moves links from the
legacy duplicate, removes that duplicate through Frappe's merge path, then
renames both aggregates to the same HS identifier.

Raw historical links are still accepted at API boundaries, but no new
applicant row is created with an ``ENR-``/``LD-``/``CRMC-`` identifier after
this patch.
"""

from __future__ import annotations

import frappe
from frappe.model.rename_doc import rename_doc

from crm.fcrm.student_reference import hs_code_for_reference


def _fields(doctype: str):
	return frappe.get_meta(doctype).fields


def _copy_missing_profile_fields(source, target) -> None:
	"""Preserve non-empty legacy profile values before merging the old row."""
	excluded = {
		"name",
		"student",
		"source_lead",
		"lead_code",
		"converted_at",
		"student_identity",
	}
	for field in _fields("CRM Student"):
		if field.fieldname in excluded or field.fieldtype in {
			"Section Break",
			"Column Break",
			"Tab Break",
			"HTML",
			"Table",
			"Table MultiSelect",
		}:
			continue
		old_value = source.get(field.fieldname)
		if old_value in (None, "") or target.get(field.fieldname) not in (None, ""):
			continue
		frappe.db.set_value(
			"CRM Student", target.name, field.fieldname, old_value, update_modified=False
		)


def _reparent_child_rows(source: str, target: str) -> None:
	"""Keep child-table evidence when a legacy duplicate is merged."""
	for field in frappe.get_meta("CRM Student").get_table_fields():
		child = field.options
		if not child or not frappe.db.table_exists(child):
			continue
		frappe.db.sql(
			f"""update `tab{child}`
			set parent = %s
			where parent = %s and parenttype = 'CRM Student'""",
			(target, source),
		)


def _merge_student(source: str, target: str) -> None:
	if source == target or not frappe.db.exists("CRM Student", source):
		return
	if not frappe.db.exists("CRM Student", target):
		frappe.throw(f"Cannot merge Student {source}; target {target} does not exist.", frappe.ValidationError)
	source_doc = frappe.get_doc("CRM Student", source)
	target_doc = frappe.get_doc("CRM Student", target)
	_copy_missing_profile_fields(source_doc, target_doc)
	_reparent_child_rows(source, target)
	rename_doc(
		"CRM Student",
		source,
		target,
		force=True,
		merge=True,
		ignore_permissions=True,
		rebuild_search=False,
		show_alert=False,
	)


def _student_for_lead(lead: dict) -> str | None:
	rows = frappe.get_all(
		"CRM Student",
		filters={"student": lead["name"]},
		fields=["name", "source_lead", "lead_code"],
		order_by="source_lead desc, lead_code desc, creation asc, name asc",
		limit_page_length=0,
		ignore_permissions=True,
	)
	# Prefer the row created by the conversion contract. A legacy Lead.student
	# link can still point to the older Contact-shaped duplicate.
	for row in rows:
		if row.get("source_lead") == lead["name"] or row.get("lead_code") == lead.get("lead_code"):
			return row.name
	linked = lead.get("converted_student") or lead.get("student")
	if linked and frappe.db.exists("CRM Student", linked):
		return linked
	return rows[0].name if rows else None


def _student_duplicates_for_lead(lead: dict, canonical: str | None) -> list[str]:
	return [
		row.name
		for row in frappe.get_all(
			"CRM Student",
			filters={"student": lead["name"]},
			fields=["name"],
			limit_page_length=0,
			ignore_permissions=True,
		)
		if row.name != canonical
	]


def _rename(doctype: str, source: str, target: str) -> bool:
	if source == target or not frappe.db.exists(doctype, source):
		return False
	if frappe.db.exists(doctype, target):
		frappe.throw(
			f"Cannot unify {doctype} {source} to {target}: target already exists.",
			frappe.ValidationError,
		)
	rename_doc(
		doctype,
		source,
		target,
		force=True,
		ignore_permissions=True,
		rebuild_search=False,
		show_alert=False,
	)
	return True


def _set_unified_links(lead_name: str, student_name: str | None) -> None:
	if frappe.db.exists("CRM Lead", lead_name):
		updates = {"lead_code": lead_name}
		if student_name and frappe.get_meta("CRM Lead").has_field("student"):
			updates["student"] = student_name
		if student_name and frappe.get_meta("CRM Lead").has_field("converted_student"):
			updates["converted_student"] = student_name
		frappe.db.set_value("CRM Lead", lead_name, updates, update_modified=False)
	if student_name and frappe.db.exists("CRM Student", student_name):
		frappe.db.set_value("CRM Student", student_name, "lead_code", lead_name, update_modified=False)
		frappe.db.set_value("CRM Student", student_name, "source_lead", lead_name, update_modified=False)
		frappe.db.set_value("CRM Student", student_name, "student", lead_name, update_modified=False)


def execute():
	"""Idempotently migrate every ENR/LD applicant identity to HS."""
	leads = frappe.get_all(
		"CRM Lead",
		fields=["name", "lead_code", "admission_year", "student", "converted_student"],
		order_by="creation asc, name asc",
		limit_page_length=0,
		ignore_permissions=True,
	)
	renamed_leads = 0
	renamed_students = 0
	merged_students = 0
	for lead in leads:
		target = hs_code_for_reference(lead.name, lead.admission_year) or hs_code_for_reference(
			lead.lead_code, lead.admission_year
		)
		if not target:
			continue

		canonical = _student_for_lead(lead)
		if canonical:
			for duplicate in _student_duplicates_for_lead(lead, canonical):
				_merge_student(duplicate, canonical)
				merged_students += 1
			if _rename("CRM Student", canonical, target):
				renamed_students += 1
			canonical = target

		if _rename("CRM Lead", lead.name, target):
			renamed_leads += 1
		_set_unified_links(target, canonical)

	frappe.clear_cache(doctype="CRM Lead")
	frappe.clear_cache(doctype="CRM Student")
	return {
		"renamed_leads": renamed_leads,
		"renamed_students": renamed_students,
		"merged_students": merged_students,
	}
