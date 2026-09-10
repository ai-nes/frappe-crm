"""Frappe-backed availability checks for the CRM Action Type catalog."""

from __future__ import annotations

import frappe

from crm.fcrm.action_type_catalog import (
	ACTION_TYPE_CODES,
	LEGACY_ACTION_TYPE_ALIASES,
	LEGACY_RECOMMENDATION_ONLY,
	SUPPORTED_ACTION_TYPES,
	SUPPORTED_RECOMMENDATION_ACTION_TYPES,
)


def _catalog_doctype_exists() -> bool:
	try:
		return bool(frappe.db.exists("DocType", "CRM Action"))
	except Exception:
		return False


def _action_type_doctype_exists() -> bool:
	try:
		return bool(frappe.db.exists("DocType", "CRM Action Type"))
	except Exception:
		return False


def is_available_action_type(action_type: str | None) -> bool:
	"""Return whether an enabled Action and its parent Type can be used."""
	if not action_type:
		return False
	if _catalog_doctype_exists():
		row = frappe.db.get_value("CRM Action", action_type, ["enabled", "action_type"])
		if row is not None:
			action_enabled, parent_type = row
			if not frappe.utils.cint(action_enabled):
				return False
			if not parent_type or not _action_type_doctype_exists():
				return False
			parent_enabled = frappe.db.get_value("CRM Action Type", parent_type, "enabled")
			return parent_enabled is not None and bool(frappe.utils.cint(parent_enabled))
	if action_type in LEGACY_ACTION_TYPE_ALIASES - ACTION_TYPE_CODES:
		return True
	if not _catalog_doctype_exists():
		return action_type in ACTION_TYPE_CODES
	# During migration the DocType exists before its seed patch runs. Keep the
	# canonical vocabulary writable so existing callers are not bricked between
	# schema creation and catalog seeding.
	return action_type in ACTION_TYPE_CODES and frappe.db.count("CRM Action") == 0


def is_available_recommendation_action(action_type: str | None) -> bool:
	if not action_type:
		return False
	if action_type in LEGACY_RECOMMENDATION_ONLY:
		return True
	if action_type not in SUPPORTED_RECOMMENDATION_ACTION_TYPES and not _catalog_doctype_exists():
		return False
	return is_available_action_type(action_type)


def available_action_types() -> list[str]:
	"""Return enabled built-in and custom Action codes in display order."""
	if not _catalog_doctype_exists():
		return sorted(ACTION_TYPE_CODES)
	if not _action_type_doctype_exists():
		return []
	rows = frappe.get_all(
		"CRM Action",
		filters={"enabled": 1},
		fields=["code", "action_type"],
		order_by="sort_order asc",
		limit_page_length=0,
		ignore_permissions=True,
	)
	if not rows and frappe.db.count("CRM Action") == 0:
		return sorted(ACTION_TYPE_CODES)
	type_names = {row.action_type for row in rows if row.action_type}
	enabled_types = set()
	if type_names:
		enabled_types = {
			row.name
			for row in frappe.get_all(
				"CRM Action Type",
				filters={"name": ["in", list(type_names)], "enabled": 1},
				fields=["name"],
				limit_page_length=0,
				ignore_permissions=True,
			)
		}
	return [
		row.code
		for row in rows
		if row.action_type in enabled_types
	]
