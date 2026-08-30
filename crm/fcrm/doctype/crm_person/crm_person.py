import frappe
from frappe.model.document import Document

from crm.fcrm.school_domain_permissions import (
	default_portfolio,
	has_portfolio_permission,
	portfolio_condition,
	validate_portfolio_update,
)


class CRMPerson(Document):
	def before_insert(self):
		default_portfolio(self)

	def validate(self):
		validate_portfolio_update(self)
		if self.stakeholder_role:
			category = frappe.db.get_value("CRM Term", self.stakeholder_role, "category")
			if category and category != "stakeholder_role":
				frappe.throw("Stakeholder Role must use a stakeholder_role term.", frappe.ValidationError)

	@staticmethod
	def get_permission_query_conditions(user=None, doctype=None):
		if doctype not in (None, "CRM Person"):
			return "1=0"
		return portfolio_condition("CRM Person", user)

	@staticmethod
	def has_permission(doc, user=None, permission_type=None, ptype=None):
		return has_portfolio_permission(doc, user, permission_type, ptype)

	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Full Name", "type": "Data", "key": "full_name", "width": "16rem"},
			{"label": "Role", "type": "Data", "key": "role", "width": "10rem"},
			{"label": "Stakeholder Role", "type": "Link", "key": "stakeholder_role", "options": "CRM Term", "width": "12rem"},
			{"label": "High School", "type": "Link", "key": "high_school", "options": "CRM High School", "width": "14rem"},
			{"label": "Relationship", "type": "Select", "key": "relationship_status", "width": "10rem"},
			{"label": "Owner", "type": "Link", "key": "owner_staff", "options": "CRM Staff", "width": "12rem"},
			{"label": "Phone", "type": "Data", "key": "phone", "width": "10rem"},
			{"label": "Email", "type": "Data", "key": "email", "width": "14rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = [
			"name", "full_name", "role", "stakeholder_role", "high_school", "relationship_status",
			"owner_staff", "phone", "email", "modified",
		]
		return {"columns": columns, "rows": rows}


def get_permission_query_conditions(user=None, doctype=None):
	return portfolio_condition("CRM Person", user)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	return has_portfolio_permission(doc, user, permission_type, ptype)
