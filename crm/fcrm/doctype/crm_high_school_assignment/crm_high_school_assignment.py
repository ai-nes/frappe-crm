# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CRMHighSchoolAssignment(Document):
	def before_validate(self):
		self._sync_zone_from_high_school()

	def validate(self):
		self._validate_staff_team_membership()
		self._validate_high_school_active()
		self._validate_zone_owned_by_team()
		self._validate_no_duplicate_active_assignment()

	def _high_school_info(self):
		if not hasattr(self, "_cached_high_school_info"):
			self._cached_high_school_info = (
				frappe.db.get_value(
					"CRM High School", self.high_school, ["ward", "is_active"], as_dict=True
				)
				if self.high_school
				else None
			)
		return self._cached_high_school_info

	def _sync_zone_from_high_school(self):
		info = self._high_school_info()
		if not info or not info.ward:
			self.zone = None
			return
		self.zone = frappe.db.get_value("CRM Ward", info.ward, "zone")

	def _validate_staff_team_membership(self):
		is_member = frappe.db.exists(
			"CRM Team Membership", {"parent": self.staff, "parenttype": "CRM Staff", "team": self.team}
		)
		if not is_member:
			frappe.throw(
				_("Team Member {0} does not have an active membership in Team {1}.").format(
					self.staff, self.team
				),
				frappe.ValidationError,
			)

	def _validate_high_school_active(self):
		info = self._high_school_info()
		if not info or not info.is_active:
			frappe.throw(
				_("Cannot assign an inactive High School ({0}).").format(self.high_school),
				frappe.ValidationError,
			)

	def _validate_zone_owned_by_team(self):
		if not self.zone:
			frappe.throw(
				_("High School {0} has no Zone resolved via its Ward — fix the geography chain first.").format(
					self.high_school
				),
				frappe.ValidationError,
			)
		owns_zone = frappe.db.exists(
			"CRM Team Zone Assignment", {"zone": self.zone, "team": self.team, "status": "Active"}
		)
		if not owns_zone:
			frappe.throw(
				_(
					"Team {0} does not currently own Zone {1} — cannot assign a High School outside "
					"the Team's Zone scope."
				).format(self.team, self.zone),
				frappe.ValidationError,
			)

	def _validate_no_duplicate_active_assignment(self):
		if self.status != "Active":
			return
		filters = {"staff": self.staff, "high_school": self.high_school, "status": "Active"}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("CRM High School Assignment", filters):
			frappe.throw(
				_("Team Member {0} already has an active assignment for High School {1}.").format(
					self.staff, self.high_school
				),
				frappe.DuplicateEntryError,
			)
