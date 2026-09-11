"""Ensure the default high-school area lookup rows exist on every site."""

import frappe

from crm.fcrm.reference_catalog import REFERENCE_CATALOG

DEFAULT_SCHOOL_AREA_CODES = {"KV1", "KV2", "KV3"}


def execute():
	if not frappe.db.exists("DocType", "CRM School Area"):
		return

	for row in REFERENCE_CATALOG["CRM School Area"]:
		if row["code"] not in DEFAULT_SCHOOL_AREA_CODES:
			continue
		if frappe.db.exists("CRM School Area", row["code"]):
			continue
		frappe.get_doc({"doctype": "CRM School Area", **row}).insert(ignore_permissions=True)

	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()
