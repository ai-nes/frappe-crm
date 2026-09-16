"""Normalize CRM Province codes to the canonical ``VN_*`` source identifiers."""

from __future__ import annotations

import frappe

from crm.patches.v1_0.align_lead_mapping_contract import (
	PROVINCES,
	_normalized,
	_province_code,
)

CANONICAL_PROVINCE_NAMES = {_normalized(name): name for name, _ in PROVINCES}
LEGACY_HCMC_NAME = "Ho Chi Minh City"
CANONICAL_HCMC_NAME = "Hồ Chí Minh"


def _canonical_code(row: dict) -> str | None:
	key = _normalized(row.get("province_name") or row.get("name"))
	canonical_name = CANONICAL_PROVINCE_NAMES.get(key)
	return _province_code(canonical_name) if canonical_name else None


def _repoint_province_links(source: str, target: str) -> None:
	fields = frappe.get_all(
		"DocField",
		filters={"fieldtype": "Link", "options": "CRM Province"},
		fields=["parent", "fieldname"],
		limit_page_length=0,
	)
	fields.extend(
		frappe.get_all(
			"Custom Field",
			filters={"fieldtype": "Link", "options": "CRM Province"},
			fields=["dt as parent", "fieldname"],
			limit_page_length=0,
		)
	)
	for field in fields:
		doctype = field.parent
		fieldname = field.fieldname
		if not frappe.db.has_column(doctype, fieldname):
			continue
		frappe.db.sql(
			f"UPDATE `tab{doctype}` SET `{fieldname}` = %s WHERE `{fieldname}` = %s",
			(target, source),
		)

	if frappe.db.has_column("CRM Ward", "province_name"):
		frappe.db.sql(
			"UPDATE `tabCRM Ward` SET province_name = %s WHERE province_name = %s",
			(target, source),
		)


def _merge_legacy_hcmc() -> None:
	legacy_exists = frappe.db.exists("CRM Province", LEGACY_HCMC_NAME)
	if not legacy_exists:
		return

	canonical_exists = frappe.db.exists("CRM Province", CANONICAL_HCMC_NAME)
	if not canonical_exists:
		frappe.rename_doc(
			"CRM Province",
			LEGACY_HCMC_NAME,
			CANONICAL_HCMC_NAME,
			force=True,
			show_alert=False,
		)
		return

	_repoint_province_links(LEGACY_HCMC_NAME, CANONICAL_HCMC_NAME)
	frappe.delete_doc("CRM Province", LEGACY_HCMC_NAME, force=True, ignore_permissions=True)


def execute():
	_merge_legacy_hcmc()

	for row in frappe.get_all(
		"CRM Province",
		fields=["name", "province_name", "province_code"],
		limit_page_length=0,
	):
		code = _canonical_code(row)
		if not code or code == row.province_code:
			continue

		conflict = frappe.db.get_value(
			"CRM Province",
			{"province_code": code, "name": ["!=", row.name]},
			"name",
		)
		if conflict:
			raise RuntimeError(
				f"Cannot normalize province {row.name!r} to {code!r}: code is used by {conflict!r}"
			)
		frappe.db.set_value("CRM Province", row.name, "province_code", code, update_modified=False)

	frappe.db.commit()
