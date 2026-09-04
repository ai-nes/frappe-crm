# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate


class CRMTeamZoneAssignment(Document):
	def validate(self):
		if not self.revision:
			self.revision = 1
		if self.effective_until and getdate(self.effective_from) > getdate(self.effective_until):
			frappe.throw(_("Effective Until must not be before Effective From."), frappe.ValidationError)
		if self.status == "Active":
			self._validate_team_has_active_member()

	def before_save(self):
		if self.status == "Active":
			self._retire_conflicting_active_rows()

	def on_update(self):
		self._sync_zone_current_team()

	def on_trash(self):
		frappe.throw(_("Team Zone assignments are append-only. Retire the row instead of deleting it."), frappe.PermissionError)

	def _validate_team_has_active_member(self):
		has_active_member = frappe.db.sql(
			"""
			SELECT 1
			FROM `tabCRM Team Membership` m
			JOIN `tabCRM Staff` s ON s.name = m.parent
			WHERE m.team = %s AND s.is_active = 1
			LIMIT 1
			""",
			(self.team,),
		)
		if not has_active_member:
			frappe.throw(
				_("Cannot activate this assignment: Team {0} has no active Team Member.").format(self.team),
				frappe.ValidationError,
			)

	def _retire_conflicting_active_rows(self):
		"""BR-TEAM-03/04/05: a Zone is owned by only one Team at a time. Activating
		this row auto-retires whatever other row currently holds the Zone active,
		rather than requiring a manual two-step edit, and flags that former team's
		High School Assignments for review (BR-HS-08)."""
		conflicting = frappe.get_all(
			"CRM Team Zone Assignment",
			filters={"zone": self.zone, "status": "Active", "name": ["!=", self.name or ""]},
			fields=["name", "team"],
		)
		if not conflicting:
			return

		frappe.db.sql(
			"""
			UPDATE `tabCRM Team Zone Assignment`
			SET status = 'Retired', effective_until = %s
			WHERE name IN %s
			""",
			(add_days(getdate(self.effective_from), -1), tuple(row.name for row in conflicting)),
		)

		previous_teams = {row.team for row in conflicting if row.team != self.team}
		if previous_teams:
			self._flag_high_school_assignments_for_review(previous_teams)

	def _flag_high_school_assignments_for_review(self, previous_teams):
		frappe.db.sql(
			"""
			UPDATE `tabCRM High School Assignment`
			SET needs_review = 1
			WHERE zone = %s AND team IN %s AND status = 'Active'
			""",
			(self.zone, tuple(previous_teams)),
		)

	def _sync_zone_current_team(self):
		active = frappe.db.get_value(
			"CRM Team Zone Assignment",
			{"zone": self.zone, "status": "Active"},
			"team",
		)
		frappe.db.set_value(
			"CRM Zone",
			self.zone,
			{
				"current_team": active,
				"assignment_status": "Assigned" if active else "Unassigned",
			},
			update_modified=False,
		)
