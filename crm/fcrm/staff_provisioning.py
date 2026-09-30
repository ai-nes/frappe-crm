"""Provision missing sales staff only when their organization is unambiguous."""

import frappe

from crm.fcrm.role_policy import resolve_crm_profile


def ensure_sales_staff(user_doc):
	if not user_doc.enabled or resolve_crm_profile([r.role for r in user_doc.roles]) not in {
		"sales",
		"ctv_sale",
	}:
		return None
	staff = frappe.db.get_value("CRM Staff", {"user": user_doc.name}, "name")
	if staff:
		return staff
	permissions = frappe.get_all(
		"User Permission",
		filters={"user": user_doc.name, "allow": ["in", ["CRM Campus", "CRM Department"]]},
		fields=["allow", "for_value"],
		limit_page_length=0,
	)
	campuses = {r.for_value for r in permissions if r.allow == "CRM Campus"}
	departments = {r.for_value for r in permissions if r.allow == "CRM Department"}
	choices = frappe.get_all("CRM Department", fields=["name", "campus"], limit_page_length=0)
	choices = [
		r
		for r in choices
		if r.campus and (not campuses or r.campus in campuses) and (not departments or r.name in departments)
	]
	if len(choices) != 1 or len(campuses) > 1:
		# Never guess a department or replace an existing multi-campus permission.
		return None
	full_name = user_doc.full_name or user_doc.name
	if frappe.db.exists("CRM Staff", full_name):
		full_name = user_doc.name
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Staff",
				"full_name": full_name,
				"user": user_doc.name,
				"campus": choices[0].campus,
				"department": choices[0].name,
				"is_active": 1,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)
