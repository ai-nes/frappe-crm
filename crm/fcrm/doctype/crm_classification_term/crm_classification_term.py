import re

import frappe
from frappe.model.document import Document

from crm.fcrm.segment_lifecycle import TRANSITIONS
from crm.fcrm.segment_rules import bounded_text, fail


def require_admin():
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		fail("Only administrators can manage Need and Tag definitions.", "FORBIDDEN", permission=True)


class CRMClassificationTerm(Document):
	def validate(self):
		require_admin()
		self.code = bounded_text(self.code, "code", limit=100)
		if not re.fullmatch(r"[A-Z][A-Z0-9_]*", self.code):
			fail("Term codes must use uppercase letters, digits and underscores.")
		self.label = bounded_text(self.label, "label")
		self.group_name = bounded_text(self.group_name, "group_name")
		self.description = bounded_text(self.description, "description", limit=2000, optional=True)
		if self.kind not in ("need", "tag") or self.status not in TRANSITIONS:
			fail("Unknown term kind or status.")
		if self.kind == "tag":
			reserved = {
				"HIGH",
				"MEDIUM",
				"LOW",
				"NEW",
				"QUALIFIED",
				"COUNSELING",
				"APPLIED",
				"ADMITTED",
				"ENROLLED",
				"LOST",
			}
			reserved.update(frappe.get_all("CRM Enrollment Status", pluck="name"))
			if self.code in reserved or any(
				word in self.code for word in ("POTENTIAL", "INTENT", "ADMISSION_STAGE")
			):
				fail("Tags cannot replace structured Stage, Potential or Intent classifications.")
		before = self.get_doc_before_save()
		if before:
			if before.status == "archive":
				fail("Archived terms are immutable.")
			if self.code != before.code or self.kind != before.kind:
				fail("Term code and kind are immutable; change the label instead.")
			if self.status != before.status and self.status not in TRANSITIONS[before.status]:
				fail("Invalid term status transition.")
			self.revision = int(before.revision or 0) + 1
		else:
			if self.status != "draft":
				fail("New terms must start as draft.")
			self.revision = 0

	def on_trash(self):
		require_admin()
		if self.status != "draft":
			fail("Archive published terms instead of deleting them.")
		for rules in frappe.get_all("CRM Segment", pluck="filters"):
			try:
				groups = (frappe.parse_json(rules) or {}).get("groups", [])
			except (ValueError, AttributeError):
				continue
			for group in groups:
				for condition in group.get("conditions", []):
					if condition.get("field") in ("need", "tag") and self.name in (
						condition.get("value") or []
					):
						fail("This term is referenced by a Segment; archive it instead.")

	def before_rename(self, *args, **kwargs):
		fail("Term identifiers are immutable.")
