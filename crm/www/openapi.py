import json

import frappe
from frappe import _

no_cache = 1


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access API docs"), frappe.PermissionError)


def get_data():
    from crm.api.swagger import get_openapi_spec

    frappe.response["type"] = "json"
    frappe.response["message"] = None
    spec = get_openapi_spec()
    frappe.response.update(spec)
    raise frappe.Redirect


def application(environ, start_response):
    pass
