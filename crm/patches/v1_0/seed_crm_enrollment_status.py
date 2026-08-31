import frappe

STATUSES = ["Mới", "Có triển vọng", "Đã xác nhận", "Đã nhập học", "Đã chuyển đổi", "Từ chối"]

# stage_order/stage_category are mandatory on the doctype; values mirror the
# business-confirmed mapping in patches/v1_0/backfill_enrollment_status_stage_category.py
# — keep both in sync if the classification changes.
STAGE_ORDER_AND_CATEGORY = {
	"Mới": (1, "open"),
	"Có triển vọng": (2, "open"),
	"Đã xác nhận": (3, "open"),
	"Đã nhập học": (4, "enrolled"),
	"Đã chuyển đổi": (5, "enrolled"),
	"Từ chối": (6, "lost"),
}
LIFECYCLE_STAGE = {"Mới": "Lead", "Có triển vọng": "MQL", "Đã xác nhận": "Applicant", "Đã nhập học": "Enrolled", "Đã chuyển đổi": "Enrolled", "Từ chối": "Lost"}


def execute():
	for name in STATUSES:
		if not frappe.db.exists("CRM Term", {"term_name": name, "category": "enrollment_status"}):
			order, category = STAGE_ORDER_AND_CATEGORY[name]
			frappe.get_doc({
				"doctype": "CRM Term", "term_name": name, "category": "enrollment_status",
				"sort_order": order, "metadata": {"stage_category": category, "lifecycle_stage": LIFECYCLE_STAGE[name]},
			}).insert(ignore_permissions=True)
