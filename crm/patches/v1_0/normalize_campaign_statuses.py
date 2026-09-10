"""Normalize legacy CRM Campaign statuses to the canonical workflow values."""

import frappe

STATUS_MAP = {
	"Draft": "DRAFT",
	"Approved": "UPCOMING",
	"Active": "ACTIVE",
	"Completed": "CLOSED",
	"Cancelled": "CLOSED",
}


def execute():
	for old_status, new_status in STATUS_MAP.items():
		frappe.db.set_value(
			"CRM Campaign",
			{"status": old_status},
			"status",
			new_status,
			update_modified=False,
		)
