"""
Backfill stage_order + stage_category on the 6 canonical CRM Enrollment
Status records (already seeded/cleaned up by fix_enrollment_status_cleanup).
Business-confirmed classification, not a technical guess:

- open:     Mới, Có triển vọng, Đã xác nhận
- enrolled: Đã nhập học, Đã chuyển đổi
- lost:     Từ chối
"""

import frappe

STAGE_ORDER_AND_CATEGORY = {
    "Mới": (1, "open"),
    "Có triển vọng": (2, "open"),
    "Đã xác nhận": (3, "open"),
    "Đã nhập học": (4, "enrolled"),
    "Đã chuyển đổi": (5, "enrolled"),
    "Từ chối": (6, "lost"),
}


def execute():
    if not frappe.db.exists("DocType", "CRM Enrollment Status"):
        return
    # Without this, bench migrate only ALTERs the table when tabDocType.modified
    # is stale relative to the JSON on disk — a forced reload guarantees
    # stage_order/stage_category exist before the set_value calls below run.
    frappe.reload_doc("fcrm", "doctype", "crm_enrollment_status", force=True)
    for status_name, (order, category) in STAGE_ORDER_AND_CATEGORY.items():
        if frappe.db.exists("CRM Enrollment Status", status_name):
            frappe.db.set_value(
                "CRM Enrollment Status", status_name,
                {"stage_order": order, "stage_category": category},
                update_modified=False,
            )
        else:
            frappe.log_error(
                title="backfill_enrollment_status_stage_category",
                message=f"canonical CRM Enrollment Status {status_name!r} not found — stage_category left unset",
            )
    frappe.clear_cache(doctype="CRM Enrollment Status")
