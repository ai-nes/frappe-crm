import frappe
from frappe.model.document import Document


class CRMTeam(Document):
	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Team Name", "type": "Data", "key": "team_name", "width": "16rem"},
			{"label": "Team Type", "type": "Select", "key": "team_type", "width": "10rem"},
			{"label": "Campus", "type": "Link", "key": "campus", "options": "CRM Campus", "width": "12rem"},
			{"label": "Active", "type": "Check", "key": "is_active", "width": "6rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = ["name", "team_name", "team_type", "campus", "is_active", "modified"]
		return {"columns": columns, "rows": rows}

	def on_trash(self):
		in_use = frappe.db.exists("CRM Team Membership", {"team": self.name})
		if in_use:
			frappe.throw(
				f"Không thể xoá team <b>{self.team_name}</b> vì vẫn còn nhân sự đang là thành viên. "
				"Hãy gỡ hết Team Membership liên quan trước."
			)
