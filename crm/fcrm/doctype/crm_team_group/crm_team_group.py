import frappe
from frappe import _
from frappe.model.document import Document


class CRMTeamGroup(Document):
	def validate(self):
		self._validate_province()
		self._validate_deactivation()

	def _validate_province(self):
		if self.province and not frappe.db.exists("CRM Province", self.province):
			frappe.throw(_("Tỉnh của Group không tồn tại."), frappe.ValidationError)
		# Existing legacy Groups may be missing the new province until an
		# administrator completes their setup. New active Groups cannot be
		# created in that state.
		if self.is_new() and self.is_active and not self.province:
			frappe.throw(
				_("Group đang hoạt động phải được gắn với một tỉnh."),
				frappe.ValidationError,
			)
		if self.province and self.is_active:
			other_group = frappe.db.get_value(
				"CRM Team Group",
				{
					"province": self.province,
					"is_active": 1,
					"name": ["!=", self.name or ""],
				},
				"name",
			)
			if other_group:
				frappe.throw(
					_("Tỉnh này đã có Group đang hoạt động: {0}.").format(other_group),
					frappe.ValidationError,
				)

	def _validate_deactivation(self):
		if self.is_active:
			return
		previous = self.get_doc_before_save()
		if not previous or not previous.is_active:
			return
		active_teams = frappe.get_all(
			"CRM Team",
			filters={"group": self.name, "is_active": 1},
			pluck="name",
		)
		if active_teams:
			frappe.throw(
				_(
					"Không thể ngừng hoạt động nhóm <b>{0}</b> vì còn {1} đội đang hoạt động. "
					"Hãy ngừng hoặc chuyển các đội trước."
				).format(self.group_name, len(active_teams)),
				frappe.ValidationError,
			)

	def on_trash(self):
		if frappe.db.exists("CRM Team", {"group": self.name}):
			frappe.throw(
				_("Không thể xoá nhóm <b>{0}</b> vì vẫn còn đội trực thuộc.").format(self.group_name)
			)
