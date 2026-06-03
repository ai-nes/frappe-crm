import frappe
from frappe.model.document import Document


class Staff(Document):
	def on_update(self):
		if self.department:
			campus = frappe.db.get_value("Department", self.department, "campus")
			if campus and campus != self.campus:
				self.db_set("campus", campus)
