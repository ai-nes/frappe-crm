"""Swap the public names of the legacy lead and student DocTypes safely."""

import frappe
from frappe.model.rename_doc import rename_doc

RENAMES = (
	("CRM Student", "CRM Lead"),
	("CRM Contact", "CRM Student"),
)


def execute():
	frappe.flags.ignore_route_conflict_validation = True
	try:
		_remove_failed_plural_sync_artifact()
		for old, new in RENAMES:
			_rename_if_needed(old, new)
		frappe.clear_cache()
	finally:
		frappe.flags.ignore_route_conflict_validation = False


def _remove_failed_plural_sync_artifact():
	"""Remove only the empty DocType created by the interrupted local sync."""
	if not frappe.db.exists("DocType", "CRM Students"):
		return
	if not frappe.db.exists("DocType", "CRM Contacts"):
		return
	if frappe.db.count("CRM Students"):
		frappe.throw(
			"CRM Students contains data and cannot be removed automatically; "
			"resolve the duplicate DocType before rerunning the migration.",
			frappe.ValidationError,
		)
	frappe.delete_doc("DocType", "CRM Students", force=True, ignore_permissions=True)


def _rename_if_needed(old, new):
	old_exists = frappe.db.exists("DocType", old)
	new_exists = frappe.db.exists("DocType", new)

	if not old_exists and not new_exists:
		# Fresh installations will create the new JSON-defined DocTypes during
		# model sync immediately after this pre-model-sync patch.
		return
	if not old_exists:
		return
	if new_exists:
		frappe.throw(
			f"Cannot rename {old} to {new}: both DocTypes already exist. "
			"Resolve the duplicate before rerunning the migration.",
			frappe.ValidationError,
		)

	rename_doc(
		"DocType",
		old,
		new,
		force=True,
		ignore_permissions=True,
		show_alert=False,
		rebuild_search=False,
	)
