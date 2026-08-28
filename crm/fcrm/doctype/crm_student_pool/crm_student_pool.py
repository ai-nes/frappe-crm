import frappe
from frappe.model.document import Document


class CRMStudentPool(Document):
	def validate(self):
		if self.team and self.campus:
			team_campus = frappe.db.get_value("CRM Team", self.team, "campus")
			if team_campus and team_campus != self.campus:
				frappe.throw("Student Pool campus must match its Team campus")
