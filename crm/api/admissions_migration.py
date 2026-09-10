"""Admin-only, read-only baseline profiling for the admissions ERD rollout."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from crm.fcrm.admissions_migration import LEGACY_PROFILE_FIELDS, build_baseline_report


def _require_admin() -> None:
	user = getattr(getattr(frappe, "session", None), "user", None)
	if user == "Administrator":
		return
	if user and "System Manager" in frappe.get_roles(user):
		return
	frappe.throw(_("Only an administrator may profile admissions migration data."), frappe.PermissionError)


def _read_rows(doctype: str, fields: tuple[str, ...]) -> list[dict[str, Any]]:
	if not frappe.db.exists("DocType", doctype):
		return []
	meta_fields = {field.fieldname for field in frappe.get_meta(doctype).fields}
	selected = ["name", *[field for field in fields if field in meta_fields]]
	return frappe.get_all(doctype, fields=selected, limit_page_length=0, ignore_permissions=True)


@frappe.whitelist()
def profile_legacy_data() -> dict[str, Any]:
	"""Return the migration baseline; this endpoint never mutates source data."""

	_require_admin()
	rows = {
		doctype: _read_rows(doctype, fields)
		for doctype, fields in LEGACY_PROFILE_FIELDS.items()
	}
	return build_baseline_report(rows)
