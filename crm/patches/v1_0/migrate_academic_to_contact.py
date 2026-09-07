"""
Re-parent academic fields from CRM Student to CRM Student.

cohort_start_year and cohort_end_year were added to tabCRM Student by mistake
and are now defined on CRM Contact instead. This patch drops the stale columns
and updates the parenttype on any existing child table rows.
"""

import frappe


def execute():
    # Drop stale integer columns from tabCRM Student if they still exist
    for col in ("cohort_start_year", "cohort_end_year"):
        if frappe.db.has_column("CRM Lead", col):
            frappe.db.sql(f"ALTER TABLE `tabCRM Lead` DROP COLUMN `{col}`")

    # Re-parent child table rows that still point at CRM Lead
    for child_doctype in (
        "CRM Student Academic Result",
        "CRM Student Language Certificate",
    ):
        frappe.db.sql(
            f"""UPDATE `tab{child_doctype}`
                SET parenttype = 'CRM Student'
                WHERE parenttype = 'CRM Lead'"""
        )

    # Force Frappe to pick up the updated JSON schemas
    for module, doctype in (
        ("fcrm", "crm_contact"),
        ("fcrm", "crm_student"),
        ("fcrm", "crm_student_academic_result"),
        ("fcrm", "crm_student_language_certificate"),
    ):
        frappe.reload_doc(module, "doctype", doctype, force=True)
