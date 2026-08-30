from frappe.model.document import Document

from crm.fcrm.school_domain_permissions import (
	has_person_portfolio_permission,
	person_portfolio_condition,
)


class CRMPerson(Document):
	@staticmethod
	def get_permission_query_conditions(user=None, doctype=None):
		if doctype not in (None, "CRM Person"):
			return "1=0"
		return person_portfolio_condition(user)

	@staticmethod
	def has_permission(doc, user=None, permission_type=None, ptype=None):
		return has_person_portfolio_permission(doc, user, permission_type, ptype)

	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Full Name", "type": "Data", "key": "full_name", "width": "16rem"},
			{"label": "Phone", "type": "Data", "key": "phone", "width": "10rem"},
			{"label": "Email", "type": "Data", "key": "email", "width": "14rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = ["name", "full_name", "phone", "email", "modified"]
		return {"columns": columns, "rows": rows}


def get_permission_query_conditions(user=None, doctype=None):
	return person_portfolio_condition(user)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	return has_person_portfolio_permission(doc, user, permission_type, ptype)
