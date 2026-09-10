from frappe.model.document import Document

from crm.fcrm.controlled_catalog import ensure_group_not_referenced, validate_group


class CRMTagGroup(Document):
	def validate(self):
		validate_group(self, "tag")

	def on_trash(self):
		ensure_group_not_referenced(self, "tag")
