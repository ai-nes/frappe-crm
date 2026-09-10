from frappe.model.document import Document

from crm.fcrm.controlled_catalog import ensure_not_referenced, validate_entry


class CRMNeed(Document):
	def validate(self):
		validate_entry(self, "need")

	def on_trash(self):
		ensure_not_referenced(self, "CRM Student Need Assignment", "need")

	def before_rename(self, *args, **kwargs):
		from crm.fcrm.segment_rules import fail

		fail("Need identifiers are immutable.")
