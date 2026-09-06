"""Two-person publication adapters for Student routing/SLA policy records."""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from crm.fcrm.role_policy import capabilities_for_roles


def _caps():
	actor = frappe.session.user
	return actor, capabilities_for_roles(frappe.get_roles(actor), administrator=actor == "Administrator")


def _service_save(doc):
	previous = getattr(frappe.flags, "student_policy_service", False)
	frappe.flags.student_policy_service = True
	try:
		doc.save(ignore_permissions=True)
	finally:
		frappe.flags.student_policy_service = previous
	return doc


@frappe.whitelist(methods=["POST"])
def create_student_policy(doctype: str, values: dict) -> dict:
	actor, caps = _caps()
	if actor != "Administrator" and "student.policy.manage" not in caps:
		frappe.throw("Chỉ Quản trị hệ thống mới được tạo cách phân công.", frappe.PermissionError)
	if doctype not in {"CRM Student Routing Policy", "CRM Student SLA Policy"} or not isinstance(values, dict):
		frappe.throw("Dữ liệu cách phân công không hợp lệ.", frappe.ValidationError)
	allowed = {
		"CRM Student Routing Policy": {"policy_key", "policy_version", "campus", "student_pool", "strategy", "scoring_weights", "effective_from", "effective_until", "recipient_scope"},
		"CRM Student SLA Policy": {"policy_key", "policy_version", "campus", "student_pool", "warning_minutes", "breach_minutes", "escalation_minutes", "pause_reasons", "maximum_pause_minutes", "recipient_strategy", "effective_from", "effective_until"},
	}[doctype]
	doc = frappe.get_doc({"doctype": doctype, **{key: value for key, value in values.items() if key in allowed}})
	doc.status = "draft"
	doc.authored_by = actor
	_service_save(doc)
	frappe.db.commit()
	return {"name": doc.name, "doctype": doc.doctype, "status": doc.status, "authored_by": actor}


@frappe.whitelist(methods=["POST"])
def approve_student_policy(doctype: str, name: str) -> dict:
	actor, caps = _caps()
	if "student.policy.approve" not in caps:
		frappe.throw("Chỉ Giám đốc tuyển sinh mới được duyệt cách phân công.", frappe.PermissionError)
	if doctype not in {"CRM Student Routing Policy", "CRM Student SLA Policy"}:
		frappe.throw("Loại cách phân công không được hỗ trợ.", frappe.ValidationError)
	doc = frappe.get_doc(doctype, name)
	doc.status = "active"
	doc.approved_by = actor
	doc.approved_at = now_datetime()
	_service_save(doc)
	frappe.db.commit()
	return {"name": doc.name, "doctype": doc.doctype, "status": doc.status, "approved_by": actor}


@frappe.whitelist(methods=["POST"])
def retire_student_policy(doctype: str, name: str) -> dict:
	actor, caps = _caps()
	if actor != "Administrator" and "student.policy.manage" not in caps:
		frappe.throw("Chỉ Quản trị hệ thống mới được dừng cách phân công.", frappe.PermissionError)
	if doctype not in {"CRM Student Routing Policy", "CRM Student SLA Policy"}:
		frappe.throw("Loại cách phân công không được hỗ trợ.", frappe.ValidationError)
	doc = frappe.get_doc(doctype, name)
	doc.status = "retired"
	_service_save(doc)
	frappe.db.commit()
	return {"name": doc.name, "doctype": doc.doctype, "status": doc.status}
