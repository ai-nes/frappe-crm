import frappe
from frappe import _
from frappe.model.document import Document


class CRMTerritory(Document):
	def validate(self):
		if self.parent_territory and self.parent_territory == self.name:
			frappe.throw(_("A territory cannot be its own parent."))
		if self.effective_from and self.effective_until and self.effective_from > self.effective_until:
			frappe.throw(_("Effective From must not be after Effective Until."))
