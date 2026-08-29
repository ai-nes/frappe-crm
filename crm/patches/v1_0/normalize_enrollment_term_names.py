"""Keep admission-status Link values human-readable in Desk.

CRM Term is shared by several catalogues. Older migrations created
``enrollment_status:<term>`` names when a Lead Status had already claimed the
same plain name. Enrollment Status is used as a direct Desk selection, so it
owns the plain Vietnamese name; the colliding Lead Status is renamed instead.
Frappe's rename operation rewrites all Link references atomically.
"""

from __future__ import annotations

import frappe
from frappe.model.rename_doc import rename_doc


CANONICAL_STATUSES = (
	"Mới",
	"Có triển vọng",
	"Đã xác nhận",
	"Đã nhập học",
	"Đã chuyển đổi",
	"Từ chối",
)


def _term_name(category: str, term_name: str) -> str | None:
	return frappe.db.get_value("CRM Term", {"category": category, "term_name": term_name}, "name")


def repair_enrollment_status_references():
	"""Restore admission fields touched while a colliding Lead Status is renamed."""
	for term_name in CANONICAL_STATUSES:
		if not frappe.db.exists("CRM Term", {"name": term_name, "category": "enrollment_status"}):
			continue

		legacy_name = f"lead_status:{term_name}"
		for doctype in ("CRM Student", "CRM Contact"):
			if frappe.db.exists("DocType", doctype):
				frappe.db.set_value(
					doctype,
					{"enrollment_status": legacy_name},
					"enrollment_status",
					term_name,
					update_modified=False,
				)


def execute():
	if not frappe.db.exists("DocType", "CRM Term"):
		return

	# This is a one-off canonicalization migration, not a user-initiated rename.
	# Keep governance active everywhere else.
	frappe.flags.crm_governance_change = True
	try:
		for term_name in CANONICAL_STATUSES:
			enrollment_name = _term_name("enrollment_status", term_name)
			if not enrollment_name or enrollment_name == term_name:
				continue

			plain_category = frappe.db.get_value("CRM Term", term_name, "category")
			if plain_category == "lead_status":
				lead_target = f"lead_status:{term_name}"
				if not frappe.db.exists("CRM Term", lead_target):
					rename_doc("CRM Term", term_name, lead_target, force=True, ignore_permissions=True)
			elif plain_category:
				# Do not overwrite a value owned by an unexpected catalogue. Its data
				# owner must resolve that conflict before an admissions status is renamed.
				continue

			if not frappe.db.exists("CRM Term", term_name):
				rename_doc("CRM Term", enrollment_name, term_name, force=True, ignore_permissions=True)

		repair_enrollment_status_references()
	finally:
		frappe.flags.crm_governance_change = False
