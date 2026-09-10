import frappe
from frappe import _
from frappe.model.document import Document


class CRMForecastScenario(Document):
	def before_validate(self):
		if self.run and not self.planning_scope:
			self.planning_scope = frappe.db.get_value("CRM Forecast Run", self.run, "planning_scope")

	def validate(self):
		if not self.planning_scope:
			frappe.throw(_("Planning Scope is required."), frappe.ValidationError)
		run_scope = frappe.db.get_value("CRM Forecast Run", self.run, "planning_scope")
		if run_scope and run_scope != self.planning_scope:
			frappe.throw(_("Scenario Planning Scope must match its Forecast Run."), frappe.ValidationError)
