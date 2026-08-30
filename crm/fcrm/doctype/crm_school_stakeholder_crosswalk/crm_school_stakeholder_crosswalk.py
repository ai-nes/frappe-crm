from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.admissions_migration import stable_fingerprint


class CRMSchoolStakeholderCrosswalk(Document):
	def before_validate(self):
		if not self.crosswalk_key and self.legacy_doctype and self.legacy_name:
			self.crosswalk_key = f"{self.legacy_doctype}:{self.legacy_name}"
		if not self.schema_version:
			self.schema_version = "admissions-erd-v2"
		if not self.idempotency_fingerprint:
			self.idempotency_fingerprint = stable_fingerprint(
				"school-stakeholder-crosswalk",
				self.legacy_doctype,
				self.legacy_name,
				self.contact,
				self.person,
				self.match_method,
			)

	def validate(self):
		if not 0 <= float(self.confidence or 0) <= 100:
			frappe.throw(_("Confidence must be between 0 and 100."), frappe.ValidationError)
		if self.status == "Mapped" and (self.reviewer_outcome != "Accepted" or not self.person):
			frappe.throw(_("A mapped crosswalk requires an accepted Person match."), frappe.ValidationError)
		if self.status == "Quarantined" and self.reviewer_outcome == "Accepted":
			frappe.throw(_("An accepted match cannot remain quarantined."), frappe.ValidationError)

	def on_trash(self):
		frappe.throw(_("Crosswalk evidence is append-only."), frappe.PermissionError)
