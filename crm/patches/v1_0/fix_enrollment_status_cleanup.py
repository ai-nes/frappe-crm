"""
Clean up CRM Enrollment Status table:
- Delete any non-Vietnamese / stale records (English, Pending Confirmation, etc.)
- Re-seed exactly the 6 canonical Vietnamese statuses
- Migrate CRM Student + CRM Contact rows to Vietnamese values
- Ensure CRM Lead Status "Mới" exists (required by convert_to_contact)
"""

import frappe

CANONICAL_STATUSES = ["Mới", "Có triển vọng", "Đã xác nhận", "Đã nhập học", "Đã chuyển đổi", "Từ chối"]

# Map every known non-Vietnamese value → canonical Vietnamese
MIGRATION_MAP = {
    "New": "Mới",
    "Prospect": "Có triển vọng",
    "Confirmed": "Đã xác nhận",
    "Pending Confirmation": "Đã xác nhận",
    "Enrolled": "Đã nhập học",
    "Converted": "Đã chuyển đổi",
    "Refused": "Từ chối",
    "Rejected": "Từ chối",
    "Deferred": "Từ chối",
    "Withdrawn": "Từ chối",
}


def execute():
    # 1. Migrate student + contact rows BEFORE deleting old records
    for eng, vie in MIGRATION_MAP.items():
        frappe.db.sql(
            "UPDATE `tabCRM Student` SET enrollment_status = %s WHERE enrollment_status = %s",
            (vie, eng),
        )
        frappe.db.sql(
            "UPDATE `tabCRM Contact` SET enrollment_status = %s WHERE enrollment_status = %s",
            (vie, eng),
        )

    # 2. Default blank enrollment_status to "Mới"
    frappe.db.sql(
        "UPDATE `tabCRM Student` SET enrollment_status = 'Mới' WHERE (enrollment_status IS NULL OR enrollment_status = '')"
    )
    frappe.db.sql(
        "UPDATE `tabCRM Contact` SET enrollment_status = 'Mới' WHERE (enrollment_status IS NULL OR enrollment_status = '')"
    )

    # 3. Delete all non-canonical CRM Enrollment Status records
    all_statuses = frappe.db.get_all("CRM Enrollment Status", pluck="name")
    for status in all_statuses:
        if status not in CANONICAL_STATUSES:
            frappe.delete_doc("CRM Enrollment Status", status, ignore_permissions=True, force=True)

    # 4. Insert any missing canonical statuses
    for status in CANONICAL_STATUSES:
        if not frappe.db.exists("CRM Enrollment Status", status):
            frappe.get_doc({
                "doctype": "CRM Enrollment Status",
                "status_name": status,
            }).insert(ignore_permissions=True)

    # 5. Ensure at least "Mới" exists in CRM Lead Status (needed by convert_to_contact)
    if not frappe.db.exists("CRM Lead Status", "Mới"):
        frappe.get_doc({
            "doctype": "CRM Lead Status",
            "status_name": "Mới",
        }).insert(ignore_permissions=True)

    frappe.clear_cache(doctype="CRM Enrollment Status")
    frappe.clear_cache(doctype="CRM Lead Status")
