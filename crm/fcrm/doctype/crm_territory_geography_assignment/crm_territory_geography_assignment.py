from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.admissions_migration import stable_fingerprint


class CRMTerritoryGeographyAssignment(Document):
	def before_validate(self):
		if not self.revision:
			self.revision = 1
		if not self.schema_version:
			self.schema_version = "admissions-erd"
		if (
			self.territory
			and self.geography_type
			and self.geography
			and self.effective_from
			and not self.business_key
		):
			self.business_key = "|".join(
				(
					self.territory,
					self.geography_type,
					self.geography,
					str(self.effective_from),
					str(self.revision),
				)
			)
		if not self.idempotency_fingerprint:
			self.idempotency_fingerprint = stable_fingerprint(
				"territory-geography",
				self.territory,
				self.geography_type,
				self.geography,
				self.effective_from,
				self.effective_until,
				self.revision,
			)

	def validate(self):
		if self.effective_from > self.effective_until:
			frappe.throw(_("Effective Until must not be before Effective From."), frappe.ValidationError)
		if int(self.revision or 0) < 1:
			frappe.throw(_("Revision must be positive."), frappe.ValidationError)
		if int(self.revision or 1) > 1 and not self.supersedes:
			frappe.throw(_("Supersedes is required for an assignment correction."), frappe.ValidationError)
		self._validate_active_overlap()

	def _validate_active_overlap(self):
		rows = frappe.get_all(
			"CRM Territory Geography Assignment",
			filters={"geography_type": self.geography_type, "geography": self.geography, "status": "Active"},
			fields=["name", "territory", "effective_from", "effective_until"],
			limit_page_length=0,
		)
		for row in rows:
			if (
				row.name != self.name
				and str(row.effective_from) <= str(self.effective_until)
				and str(row.effective_until) >= str(self.effective_from)
			):
				frappe.throw(
					_("An active geography cannot overlap another Territory assignment."),
					frappe.DuplicateEntryError,
				)

	def on_trash(self):
		frappe.throw(_("Territory geography assignments are append-only."), frappe.PermissionError)
