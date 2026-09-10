from frappe.model.document import Document

from crm.fcrm.controlled_catalog import ensure_not_referenced, validate_entry


class CRMTag(Document):
	def validate(self):
		validate_entry(self, "tag")

	def on_trash(self):
		ensure_not_referenced(self, "CRM Student Tag Assignment", "tag")

	def before_rename(self, *args, **kwargs):
		from crm.fcrm.segment_rules import fail

		fail("Tag identifiers are immutable.")
