import frappe

from crm.api.google_auth import providers as google_providers


@frappe.whitelist(allow_guest=True)
def oauth_providers():
	"""Backward-compatible route for the login page.

	The implementation is CRM-owned and does not read Social Login Key.
	"""
	return google_providers("/crm")
