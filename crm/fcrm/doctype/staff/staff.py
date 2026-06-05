import frappe
from frappe.model.document import Document


class Staff(Document):
	def after_insert(self):
		if self.user and self.campus:
			self._sync_campus_user_permission()

	def on_update(self):
		if self.department:
			campus = frappe.db.get_value("Department", self.department, "campus")
			if campus and campus != self.campus:
				self.db_set("campus", campus)
				self.campus = campus

		if self.user and self.campus:
			self._sync_campus_user_permission()

	def _sync_campus_user_permission(self):
		existing = frappe.db.get_value(
			"User Permission",
			{"user": self.user, "allow": "CRM Campus"},
			"name",
		)
		if existing:
			frappe.db.set_value("User Permission", existing, "for_value", self.campus)
		else:
			frappe.get_doc({
				"doctype": "User Permission",
				"user": self.user,
				"allow": "CRM Campus",
				"for_value": self.campus,
				"apply_to_all_doctypes": 1,
			}).insert(ignore_permissions=True)
