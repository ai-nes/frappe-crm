"""Fail-closed guards for superseded aggregate DocTypes."""

import frappe
from frappe import _


def reject_legacy_fact_write(doctype: str):
	if not getattr(frappe.flags, "legacy_fact_migration", False):
		frappe.throw(
			_("{0} is a compatibility artifact; write CRM Campaign Performance Fact instead.").format(
				doctype
			),
			frappe.PermissionError,
		)
