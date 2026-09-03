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


def is_available_action_type(action_type: str | None) -> bool:
	"""Return whether a code can be used for a new CRM Action."""
	if not action_type or action_type not in SUPPORTED_ACTION_TYPES:
		return False
	if action_type in LEGACY_ACTION_TYPE_ALIASES - ACTION_TYPE_CODES:
		return True
	if not _catalog_doctype_exists():
		return action_type in ACTION_TYPE_CODES
	row = frappe.db.get_value("CRM Action", action_type, "enabled")
	if row is not None:
		return bool(row)
	# During migration the DocType exists before its seed patch runs. Keep the
	# canonical vocabulary writable so existing callers are not bricked between
	# schema creation and catalog seeding.
	return frappe.db.count("CRM Action") == 0


def is_available_recommendation_action(action_type: str | None) -> bool:
	if not action_type or action_type not in SUPPORTED_RECOMMENDATION_ACTION_TYPES:
		return False
	if action_type in LEGACY_RECOMMENDATION_ONLY:
		return True
	return is_available_action_type(action_type)


def available_action_types() -> list[str]:
	"""Return enabled canonical codes in the catalog's display order."""
	if not _catalog_doctype_exists():
		return sorted(ACTION_TYPE_CODES)
	rows = frappe.get_all(
		"CRM Action",
		filters={"enabled": 1},
		fields=["code"],
		order_by="sort_order asc",
		limit_page_length=0,
		ignore_permissions=True,
	)
	if not rows and frappe.db.count("CRM Action") == 0:
		return sorted(ACTION_TYPE_CODES)
	return [
		row.code
		for row in rows
	]
