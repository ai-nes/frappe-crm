from __future__ import annotations

import frappe
from frappe.model.document import Document

from crm.fcrm.school_domain_permissions import (
	default_portfolio,
	has_portfolio_permission,
	portfolio_condition,
	validate_portfolio_update,
)


class CRMSchoolStakeholder(Document):
	def before_insert(self):
		default_portfolio(self)

	def validate(self):
		validate_portfolio_update(self)
		# A scoped Promoter must not create an association merely to make an
		# otherwise out-of-scope school visible through the portfolio predicate.
		# System/governance users still pass Frappe's normal High School permission.
		if self.high_school and not frappe.has_permission("CRM High School", "read", self.high_school):
			frappe.throw("You are not permitted to link a stakeholder to this school.", frappe.PermissionError)
		if self.stakeholder_role:
			category = frappe.db.get_value("CRM Term", self.stakeholder_role, "category")
			if category and category != "stakeholder_role":
				frappe.throw("Stakeholder Role must use a stakeholder_role term.", frappe.ValidationError)
		filters = {"high_school": self.high_school, "person": self.person}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("CRM School Stakeholder", filters):
			frappe.throw(
				"This person is already linked to the selected high school.",
				frappe.DuplicateEntryError,
			)

	@staticmethod
	def get_permission_query_conditions(user=None, doctype=None):
		if doctype not in (None, "CRM School Stakeholder"):
			return "1=0"
		return portfolio_condition("CRM School Stakeholder", user)

	@staticmethod
	def has_permission(doc, user=None, permission_type=None, ptype=None):
		return has_portfolio_permission(doc, user, permission_type, ptype)

	@staticmethod
	def default_list_data():
		columns = [
			{"label": "High School", "type": "Link", "key": "high_school", "options": "CRM High School", "width": "16rem"},
			{"label": "Person", "type": "Link", "key": "person", "options": "CRM Person", "width": "14rem"},
			{"label": "Role", "type": "Link", "key": "stakeholder_role", "options": "CRM Term", "width": "12rem"},
			{"label": "Relationship", "type": "Select", "key": "relationship_status", "width": "10rem"},
			{"label": "Owner", "type": "Link", "key": "owner_staff", "options": "CRM Staff", "width": "12rem"},
		]
		return {
			"columns": columns,
			"rows": ["name", "high_school", "person", "stakeholder_role", "relationship_status", "owner_staff", "modified"],
		}


def get_permission_query_conditions(user=None, doctype=None):
	return CRMSchoolStakeholder.get_permission_query_conditions(user, doctype)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	return CRMSchoolStakeholder.has_permission(doc, user, permission_type, ptype)
