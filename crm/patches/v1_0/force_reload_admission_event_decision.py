"""Align the admission decision Student link with the canonical Student DocType."""

import frappe


def execute():
	if frappe.db.exists("DocType", "CRM Admission Event Decision"):
		frappe.reload_doc("fcrm", "doctype", "crm_admission_event_decision", force=True)
