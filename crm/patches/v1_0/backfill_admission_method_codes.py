"""Normalize legacy CRM Student admission-method labels to canonical codes."""

import re

import frappe


def _as_code(value: str) -> str:
	return re.sub(r"[^A-Z0-9]+", "_", (value or "").strip().upper()).strip("_")


def execute() -> None:
	if not frappe.db.table_exists("CRM Lead") or not frappe.db.exists(
		"DocType", "CRM Admission Method"
	):
		return
	for row in frappe.db.get_all(
		"CRM Lead", fields=["name", "admission_method"], limit_page_length=0
	):
		value = row.get("admission_method")
		if not value or frappe.db.exists("CRM Admission Method", value):
			continue
		code = _as_code(value)
		if code and frappe.db.exists("CRM Admission Method", code):
			frappe.db.set_value(
				"CRM Lead", row["name"], "admission_method", code, update_modified=False
			)
	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()
