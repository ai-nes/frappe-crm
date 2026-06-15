"""
Clean up CRM Enrollment Status table:
- Delete any non-Vietnamese / stale records (English, Pending Confirmation, etc.)
- Re-seed exactly the 6 canonical Vietnamese statuses
- Migrate CRM Student + CRM Contact rows to Vietnamese values
- Ensure CRM Lead Status "Mới" exists (required by convert_to_contact)
"""

import frappe

CANONICAL_STATUSES = ["Mới", "Có triển vọng", "Đã xác nhận", "Đã nhập học", "Đã chuyển đổi", "Từ chối"]

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

_TABLES = ["`tabCRM Student`", "`tabCRM Contact`"]


def execute():
    # 1. Bulk-migrate English → Vietnamese in one CASE WHEN per table
    when_clauses = " ".join(f"WHEN {frappe.db.escape(eng)} THEN {frappe.db.escape(vie)}" for eng, vie in MIGRATION_MAP.items())
    in_list = ", ".join(frappe.db.escape(eng) for eng in MIGRATION_MAP)
    for table in _TABLES:
        frappe.db.sql(f"""
            UPDATE {table}
            SET enrollment_status = CASE enrollment_status {when_clauses} END
            WHERE enrollment_status IN ({in_list})
        """)

    # 2. Default blank enrollment_status to "Mới"
    for table in _TABLES:
        frappe.db.sql(
            f"UPDATE {table} SET enrollment_status = 'Mới' WHERE (enrollment_status IS NULL OR enrollment_status = '')"
        )

    # 3. Delete all non-canonical CRM Enrollment Status records in one shot
    all_statuses = frappe.db.get_all("CRM Enrollment Status", pluck="name")
    stale = [s for s in all_statuses if s not in CANONICAL_STATUSES]
    if stale:
        frappe.db.delete("CRM Enrollment Status", {"name": ("in", stale)})

    # 4. Insert any missing canonical statuses
    existing = set(frappe.db.get_all("CRM Enrollment Status", pluck="name"))
    for status in CANONICAL_STATUSES:
        if status not in existing:
            frappe.get_doc({
                "doctype": "CRM Enrollment Status",
                "status_name": status,
            }).insert(ignore_permissions=True)

    # 5. Ensure "Mới" exists in CRM Lead Status (needed by convert_to_contact)
    if not frappe.db.exists("CRM Lead Status", "Mới"):
        frappe.get_doc({
            "doctype": "CRM Lead Status",
            "status_name": "Mới",
        }).insert(ignore_permissions=True)

    frappe.clear_cache(doctype="CRM Enrollment Status")
    frappe.clear_cache(doctype="CRM Lead Status")
