"""
Reset CRM High School quick filters to Province, Ward, School Name only.

School Code and School Type were auto-added filters that aren't useful for
sales lookups; Province and Ward are the fields sales actually search by.
"""

import json

import frappe

QUICK_FILTERS = ["province_name", "ward_name", "school_name"]


def execute():
    global_settings = frappe.db.exists("Global Settings", {"dt": "CRM High School", "type": "Quick Filters"})
    if not global_settings:
        return

    frappe.db.set_value("Global Settings", global_settings, "json", json.dumps(QUICK_FILTERS))
