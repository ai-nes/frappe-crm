import frappe
from frappe.model.document import Document


class CRMStaff(Document):
	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Full Name", "type": "Data", "key": "full_name", "width": "16rem"},
			{"label": "Department", "type": "Link", "key": "department", "options": "CRM Department", "width": "12rem"},
			{"label": "Campus", "type": "Link", "key": "campus", "options": "CRM Campus", "width": "12rem"},
			{"label": "User", "type": "Link", "key": "user", "options": "User", "width": "12rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = ["name", "full_name", "department", "campus", "user", "modified"]
		return {"columns": columns, "rows": rows}

	def after_insert(self):
		if self.user and self.campus:
			self._sync_campus_user_permission()

	def on_update(self):
		if self.department:
			campus = frappe.db.get_value("CRM Department", self.department, "campus")
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
