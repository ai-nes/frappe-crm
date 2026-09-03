"""Rerunnable data/index preparation for admission decisions."""
import frappe


def execute():
	if not frappe.db.exists("DocType", "CRM Admission Event Decision"):
		return
	frappe.reload_doc("fcrm", "doctype", "crm_admission_event_decision")
