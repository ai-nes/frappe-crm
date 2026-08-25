"""
Extend permissions to cover CRM Education Program (master DocType added with
the student extended attributes feature) and reload CRM Student to pick up the
new child table fields.

Child tables (CRM Student Academic Result, CRM Student Language Certificate)
carry no permissions — access is governed by the parent CRM Student DocType.

For NEW deployments: setup_crm_permissions also covers CRM Education Program
via EDUCATION_PROGRAM_PERMS in its DOCTYPE_PERMS registry. This patch handles
EXISTING deployments where setup_crm_permissions has already run.
"""

import frappe

from crm.patches.v1_0.setup_crm_permissions import apply_managed_docperms


def execute():
	frappe.reload_doc("FCRM", "doctype", "crm_education_program", force=True)
	apply_managed_docperms()
	frappe.clear_cache()
