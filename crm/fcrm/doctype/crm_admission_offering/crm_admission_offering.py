from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.admissions_canonical_contracts import validate_offering


class CRMAdmissionOffering(Document):
	def before_validate(self):
		if not self.policy_version:
			self.policy_version = "admissions-policy"
		if (
			self.admission_year
			and self.campus
			and self.major
			and self.admission_method
			and not self.offering_key
		):
			self.offering_key = "|".join(
				(self.admission_year, self.campus, self.major, self.admission_method, self.policy_version)
			)
		if not self.schema_version:
			self.schema_version = "admissions-erd"

	def validate(self):
		validate_offering(self.as_dict())
		if self.status == "Active":
			if not getattr(frappe.flags, "offering_approval_writer", False):
				frappe.throw(
					_("Offerings may only be activated by the approval command."),
					frappe.PermissionError,
				)
			if not (
				{"Administrator", "System Manager", "Admissions Director"}
				& set(frappe.get_roles(frappe.session.user))
			):
				frappe.throw(
					_("Only an Admissions Director can activate an offering."), frappe.PermissionError
				)
			self._validate_active_overlap()
		if self.status == "Active" and not self.approved_by:
			frappe.throw(_("An active offering requires an approver."), frappe.ValidationError)
		if self.status == "Active" and not self.approved_at:
			self.approved_at = frappe.utils.now_datetime()

	def _validate_active_overlap(self):
		rows = frappe.get_all(
			"CRM Admission Offering",
			filters={
				"admission_year": self.admission_year,
				"campus": self.campus,
				"major": self.major,
				"admission_method": self.admission_method,
				"status": "Active",
			},
			fields=["name", "effective_from", "effective_until"],
			limit_page_length=0,
		)
		for row in rows:
			if (
				row.name != self.name
				and str(row.effective_from) <= str(self.effective_until)
				and str(row.effective_until) >= str(self.effective_from)
			):
				frappe.throw(
					_("An active offering overlaps an existing offering for the same catalog identity."),
					frappe.DuplicateEntryError,
				)
