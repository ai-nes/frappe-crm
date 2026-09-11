"""Synchronize the admission document copy from the current enrollment mockup."""

import frappe

from crm.patches.v1_0 import (
	admission_profile_options_v2,
	seed_admission_profile_template_catalog,
)


def execute() -> None:
	seed_admission_profile_template_catalog.execute()
	admission_profile_options_v2._synchronize_standard_template()
	frappe.clear_cache(doctype="CRM Document Type")
	frappe.clear_cache(doctype="CRM Admission Profile Template")
