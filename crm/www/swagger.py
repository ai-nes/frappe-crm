import frappe
from frappe import _


no_cache = 1


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access API docs"), frappe.PermissionError)

    context.title = "API Docs"
    context.no_cache = 1
