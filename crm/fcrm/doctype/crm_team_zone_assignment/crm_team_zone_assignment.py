# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate

from crm.fcrm.utils.effective import is_effective, periods_overlap


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
		memberships = frappe.get_all(
			"CRM Team Membership",
			filters={"team": self.team, "parenttype": "CRM Staff"},
			fields=["parent", "effective_from", "effective_until"],
		)
		active_staff = {
			row.name for row in frappe.get_all("CRM Staff", filters={"is_active": 1}, fields=["name"])
		}
		has_active_member = any(
			row.get("parent") in active_staff and is_effective(row, getdate()) for row in memberships
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
			fields=["name", "team", "effective_from", "effective_until"],
		)
		conflicting = [row for row in conflicting if periods_overlap(row, self)]
		if not conflicting:
			return

		retire_before = add_days(getdate(self.effective_from), -1)
		for row in conflicting:
			# Keep a future handover visible as an effective-dated Active row. A
			# handover effective today retires the previous row immediately.
			if getdate(self.effective_from) > getdate():
				frappe.db.set_value(
					"CRM Team Zone Assignment",
					row.name,
					"effective_until",
					min(retire_before, getdate(row.effective_until))
					if row.effective_until
					else retire_before,
					update_modified=False,
				)
			else:
				frappe.db.set_value(
					"CRM Team Zone Assignment",
					row.name,
					{"status": "Retired", "effective_until": retire_before},
					update_modified=False,
				)
		self._flag_high_school_assignments_for_review(
			{row.team for row in conflicting if row.team != self.team}
		)

	def _flag_high_school_assignments_for_review(self, previous_teams):
		if not previous_teams:
			return
		frappe.db.sql(
			"""
			UPDATE `tabCRM High School Assignment`
			SET needs_review = 1
			WHERE zone = %s AND team IN %s AND status = 'Active'
			""",
			(self.zone, tuple(previous_teams)),
		)

	def _sync_zone_current_team(self):
		rows = frappe.get_all(
			"CRM Team Zone Assignment",
			filters={"zone": self.zone, "status": "Active"},
			fields=["team", "effective_from", "effective_until"],
			order_by="effective_from desc, modified desc",
		)
		active = next((row for row in rows if is_effective(row, getdate())), None)
		frappe.db.set_value(
			"CRM Zone",
			self.zone,
			{
				"current_team": active.team if active else None,
				"assignment_status": "Assigned" if active else "Unassigned",
			},
			update_modified=False,
		)
