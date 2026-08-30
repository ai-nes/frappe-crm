from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.admissions_migration import stable_fingerprint


class CRMCampaignAssignmentCrosswalk(Document):
	def before_validate(self):
		if not self.crosswalk_key and self.source_doctype and self.source_name:
			self.crosswalk_key = f"{self.source_doctype}:{self.source_name}"
		if not self.schema_version:
			self.schema_version = "admissions-erd-v2"
		if not self.idempotency_fingerprint:
			self.idempotency_fingerprint = stable_fingerprint(
				"campaign-crosswalk",
				self.source_doctype,
				self.source_name,
				self.campaign,
				self.channel_assignment,
				self.effective_from,
				self.effective_until,
			)

	def validate(self):
		if not 0 <= float(self.confidence or 0) <= 100:
			frappe.throw(_("Confidence must be between 0 and 100."), frappe.ValidationError)
		if self.effective_from and self.effective_until and self.effective_from > self.effective_until:
			frappe.throw(_("Effective Until must not be before Effective From."), frappe.ValidationError)
		if self.status == "Mapped" and (
			self.reviewer_outcome != "Accepted" or not self.campaign or not self.channel_assignment
		):
			frappe.throw(
				_("A mapped crosswalk requires an accepted Campaign and Channel Assignment."),
				frappe.ValidationError,
			)
