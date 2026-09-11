"""Move the FPT Polytechnic document into its dedicated admission method."""

from __future__ import annotations

import frappe

from crm.patches.v1_0 import ensure_admission_profile_offerings, seed_admission_profile_template_catalog

LEGACY_TEMPLATE_CODE = "FPT_POLYTECHNIC"


def execute() -> None:
	if not frappe.db.table_exists("CRM Admission Profile Template"):
		return

	seed_admission_profile_template_catalog.execute()
	_ensure_college_graduation_requirement()
	ensure_admission_profile_offerings.execute()
	_retire_unused_legacy_template()

	for doctype in (
		"CRM Admission Method",
		"CRM Document Type",
		"CRM Admission Profile Template",
		"CRM Admission Offering",
	):
		frappe.clear_cache(doctype=doctype)


def _ensure_college_graduation_requirement() -> None:
	standard_name = frappe.db.get_value(
		"CRM Admission Profile Template", {"template_code": "STANDARD"}, "name"
	)
	if not standard_name:
		return

	canonical_row = next(
		row
		for row in seed_admission_profile_template_catalog._rows("STANDARD")
		if row.get("condition_key") == "field:application.admission_method=COLLEGE_GRADUATION"
	)
	college_document_type = canonical_row["document_type"]
	template = frappe.get_doc("CRM Admission Profile Template", standard_name)
	matching_rows = [
		row
		for row in template.get("document_types") or []
		if row.get("document_type") in {college_document_type, "FPT_POLYTECHNIC_DIPLOMA"}
	]
	if matching_rows:
		_target = matching_rows[0]
		changed = False
		for fieldname, value in canonical_row.items():
			if fieldname == "doctype":
				continue
			if _target.get(fieldname) != value:
				_target.set(fieldname, value)
				changed = True
	else:
		template.append("document_types", canonical_row)
		changed = True

	if not changed:
		return

	previous_flag = getattr(frappe.flags, "admission_profile_template_admin_update", False)
	frappe.flags.admission_profile_template_admin_update = True
	try:
		template.save(ignore_permissions=True)
	finally:
		frappe.flags.admission_profile_template_admin_update = previous_flag


def _retire_unused_legacy_template() -> None:
	legacy_name = frappe.db.get_value(
		"CRM Admission Profile Template", {"template_code": LEGACY_TEMPLATE_CODE}, "name"
	)
	if not legacy_name:
		return

	for doctype, fieldname in (
		("CRM Admission Application", "profile_template"),
		("CRM Student Admission Profile", "profile_template"),
		("CRM Admission Application Special Profile", "special_profile_template"),
	):
		if frappe.db.exists(doctype, {fieldname: ["in", [legacy_name, LEGACY_TEMPLATE_CODE]]}):
			return

	frappe.db.set_value(
		"CRM Admission Profile Template",
		legacy_name,
		"status",
		"Archived",
		update_modified=False,
	)
