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

	def validate(self):
		self._derive_team_lead_flags()
		self._validate_one_primary_membership_per_context()

	def _derive_team_lead_flags(self):
		for row in self.get("team_memberships") or []:
			row.is_team_lead = row.function == "Team Leader"

	def _validate_one_primary_membership_per_context(self):
		"""One staff member may hold only one *primary* membership per
		(function, campus, term) — app-level guard only, see Phase 1 plan risks
		for the known concurrent-insert race and its DB-level mitigation.
		Campus is read from CRM Team (not stored on the membership row) since a
		team has exactly one campus."""
		rows = self.get("team_memberships") or []
		team_campus = {}
		if rows:
			team_campus = {
				t.name: t.campus
				for t in frappe.get_all(
					"CRM Team",
					filters={"name": ["in", [row.team for row in rows]]},
					fields=["name", "campus"],
				)
			}

		seen = set()
		for row in rows:
			if not row.is_primary:
				continue
			context_key = (row.function, team_campus.get(row.team), row.term)
			if context_key in seen:
				frappe.throw(
					f"Nhân sự <b>{self.full_name}</b> đã có membership chính (primary) cho "
					f"chức năng <b>{row.function}</b> tại campus <b>{team_campus.get(row.team)}</b>, "
					f"kỳ <b>{row.term or '(trống)'}</b>. "
					"Chỉ được có 1 membership chính cho mỗi tổ hợp chức năng/campus/kỳ.",
					title="Trùng Primary Membership",
				)
			seen.add(context_key)

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

		self._invalidate_scope_cache()

	def on_trash(self):
		self._invalidate_scope_cache()

	def _invalidate_scope_cache(self):
		# crm.fcrm.permissions caches user->staff and staff->teams lookups for the
		# row-level scoping hot path; a team/user change here must not leave a stale
		# scope in place for up to CACHE_TTL_SEC.
		frappe.cache().delete_value(f"crm_staff_teams::{self.name}")
		if self.user:
			frappe.cache().delete_value(f"crm_staff_name::{self.user}")

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
