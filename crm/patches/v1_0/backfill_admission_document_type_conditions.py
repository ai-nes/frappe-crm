"""Backfill canonical conditions for seeded admission document types."""

from __future__ import annotations

import frappe

from crm.patches.v1_0 import seed_admission_profile_template_catalog


def execute() -> None:
	if not frappe.db.table_exists("CRM Document Type"):
		return

	for code, _label, _category in seed_admission_profile_template_catalog.DOCUMENT_TYPES:
		document_type_name = frappe.db.get_value("CRM Document Type", {"code": code}, "name")
		if not document_type_name:
			continue
		frappe.db.set_value(
			"CRM Document Type",
			document_type_name,
			"conditional_key",
			seed_admission_profile_template_catalog.DOCUMENT_TYPE_CONDITION_KEYS.get(code),
			update_modified=False,
		)
