import frappe
from frappe import _


no_cache = 1


def get_context(context):
    if not frappe.conf.developer_mode:
        frappe.throw(_("API docs are only available in developer mode"))

    context.title = "API Docs"
    context.no_cache = 1
