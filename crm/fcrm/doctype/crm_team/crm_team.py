import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.utils.effective import is_effective


class CRMTeam(Document):
	def validate(self):
		self._validate_group()
		self._validate_team_lead()
		self._validate_deactivation_has_no_active_zones()

	def _validate_group(self):
		if not self.group:
			return
		group = frappe.db.get_value(
			"CRM Team Group", self.group, ["name", "group_name", "is_active"], as_dict=True
		)
		if not group:
			frappe.throw(_("Team Group không tồn tại."), frappe.ValidationError)
		if not group.is_active and self.is_active:
			frappe.throw(
				_("Không thể bật Team trong một Group đã ngừng hoạt động."),
				frappe.ValidationError,
			)

	def _validate_team_lead(self):
		"""Validate the organizational Team leader independently from staff role.

		A Team leader can also be Sale, CTV Sale, or Lead Sale. The ``Lead Sale``
		function describes routing capability; it does not describe the Team's
		organizational leader.
		"""
		if not self.team_lead_staff:
			return
		staff = frappe.db.get_value(
			"CRM Staff", self.team_lead_staff, ["name", "full_name", "is_active"], as_dict=True
		)
		if not staff:
			frappe.throw(_("Trưởng nhóm không tồn tại."), frappe.ValidationError)
		if not staff.is_active:
			frappe.throw(_("Trưởng nhóm phải là nhân sự đang hoạt động."), frappe.ValidationError)
		if self.name and not frappe.db.exists(
			"CRM Team Membership",
			{
				"team": self.name,
				"parent": self.team_lead_staff,
				"parenttype": "CRM Staff",
			},
		):
			frappe.throw(
				_("Trưởng nhóm phải là thành viên đang hoạt động của Team."),
				frappe.ValidationError,
			)

	def _validate_deactivation_has_no_active_zones(self):
		if self.is_active:
			return
		previous = self.get_doc_before_save()
		if not previous or not previous.is_active:
			return
		assignments = frappe.get_all(
			"CRM Team Zone Assignment",
			filters={"team": self.name, "status": "Active"},
			fields=["effective_from", "effective_until"],
		)
		if any(is_effective(row) for row in assignments):
			frappe.throw(
				_(
					"Không thể ngừng hoạt động team <b>{0}</b> vì vẫn còn Zone đang được phụ trách. "
					"Hãy chuyển giao hoặc thu hồi (retire) các Zone Assignment liên quan trước."
				).format(self.team_name),
				frappe.ValidationError,
			)

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
