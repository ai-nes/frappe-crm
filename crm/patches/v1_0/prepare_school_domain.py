"""Install the school-domain role, governed terms and new DocTypes."""

from __future__ import annotations

import frappe

SCHOOL_DOMAIN_TERMS = {
	"school_type": ("Công lập", "Tư thục"),
	"school_area": ("KV1", "KV2", "KV2_NT", "KV3"),
	"stakeholder_role": ("BGH", "Giáo viên", "Cán bộ hướng nghiệp", "Đầu mối tuyển sinh"),
	"activity_type": (
		"School Visit", "Career Talk", "Counseling", "Seminar", "Open Day", "Awareness", "Relationship Touch",
		"NCDT", "Gặp gỡ BGH", "CT Trải nghiệm Hướng nghiệp", "Họp Phụ huynh",
	),
}


def _seed_terms():
	previous = getattr(frappe.flags, "crm_governance_additive", False)
	frappe.flags.crm_governance_additive = True
	try:
		for category, names in SCHOOL_DOMAIN_TERMS.items():
			for term_name in names:
				if frappe.db.exists("CRM Term", {"term_name": term_name, "category": category}):
					continue
				frappe.get_doc(
					{
						"doctype": "CRM Term",
						"term_name": term_name,
						"category": category,
						"is_active": 1,
					}
				).insert(ignore_permissions=True)
	finally:
		frappe.flags.crm_governance_additive = previous


def execute():
	if not frappe.db.exists("Role", "Promoter"):
		frappe.get_doc({"doctype": "Role", "role_name": "Promoter", "desk_access": 1}).insert(ignore_permissions=True)
	_seed_terms()
	for doctype in (
		"crm_high_school",
		"crm_person",
		"crm_high_school_annual_snapshot",
		"crm_school_activity",
	):
		frappe.reload_doc("fcrm", "doctype", doctype, force=True)
	frappe.clear_cache()
