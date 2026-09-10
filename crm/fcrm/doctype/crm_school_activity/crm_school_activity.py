from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate

from crm.fcrm.school_domain_permissions import (
	default_portfolio,
	has_portfolio_permission,
	portfolio_condition,
	validate_portfolio_update,
)


class CRMSchoolActivity(Document):
	def before_insert(self):
		default_portfolio(self)
		if not self.activity_date:
			self.activity_date = nowdate()

	def validate(self):
		validate_portfolio_update(self)
		if self.stakeholder and self.high_school:
			stakeholder_school = frappe.db.get_value("CRM School Stakeholder", self.stakeholder, "high_school")
			if stakeholder_school and stakeholder_school != self.high_school:
				frappe.throw("The stakeholder must belong to the selected high school.", frappe.ValidationError)
		for fieldname in ("attendance", "prospect_count", "contact_count", "application_count"):
			if self.get(fieldname) not in (None, "") and int(self.get(fieldname)) < 0:
				frappe.throw(f"{fieldname} cannot be negative.", frappe.ValidationError)
		if self.activity_cost not in (None, "") and float(self.activity_cost) < 0:
			frappe.throw("activity_cost cannot be negative.", frappe.ValidationError)
		for fieldname in ("expected_enrollment_min", "expected_enrollment_max", "forecast_sample_size"):
			if self.get(fieldname) not in (None, "") and int(self.get(fieldname)) < 0:
				frappe.throw(f"{fieldname} cannot be negative.", frappe.ValidationError)
		if (
			self.expected_enrollment_min not in (None, "")
			and self.expected_enrollment_max not in (None, "")
			and int(self.expected_enrollment_min) > int(self.expected_enrollment_max)
		):
			frappe.throw("Expected enrollment minimum cannot exceed maximum.", frappe.ValidationError)
		if self.forecast_confidence not in (None, "") and not 0 <= float(self.forecast_confidence) <= 100:
			frappe.throw("forecast_confidence must be between 0 and 100.", frappe.ValidationError)

	@staticmethod
	def default_list_data():
		columns = [
			{"label": "High School", "type": "Link", "key": "high_school", "options": "CRM High School", "width": "16rem"},
			{"label": "Date", "type": "Date", "key": "activity_date", "width": "9rem"},
			{"label": "Activity", "type": "Link", "key": "activity_type", "options": "CRM School Activity Type", "width": "12rem"},
			{"label": "Status", "type": "Select", "key": "status", "width": "9rem"},
			{"label": "Owner", "type": "Link", "key": "owner_staff", "options": "CRM Staff", "width": "12rem"},
		]
		rows = ["name", "high_school", "activity_date", "activity_type", "status", "outcome", "owner_staff", "application_count", "modified"]
		return {"columns": columns, "rows": rows}


def get_permission_query_conditions(user=None, doctype=None):
	return portfolio_condition("CRM School Activity", user)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	return has_portfolio_permission(doc, user, permission_type, ptype)
