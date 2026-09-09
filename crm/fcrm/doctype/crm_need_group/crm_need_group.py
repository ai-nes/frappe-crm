from frappe.model.document import Document

from crm.fcrm.controlled_catalog import ensure_group_not_referenced, validate_group


class CRMNeedGroup(Document):
	def validate(self):
		validate_group(self, "need")

	def on_trash(self):
		ensure_group_not_referenced(self, "need")
