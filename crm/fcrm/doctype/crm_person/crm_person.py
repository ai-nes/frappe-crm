from frappe.model.document import Document


class CRMPerson(Document):
	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Full Name", "type": "Data", "key": "full_name", "width": "16rem"},
			{"label": "Role", "type": "Data", "key": "role", "width": "10rem"},
			{"label": "High School", "type": "Link", "key": "high_school", "options": "CRM High School", "width": "14rem"},
			{"label": "Phone", "type": "Data", "key": "phone", "width": "10rem"},
			{"label": "Email", "type": "Data", "key": "email", "width": "14rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = ["name", "full_name", "role", "high_school", "phone", "email", "modified"]
		return {"columns": columns, "rows": rows}
