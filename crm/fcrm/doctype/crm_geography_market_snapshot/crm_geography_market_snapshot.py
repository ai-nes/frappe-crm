import frappe
from frappe import _
from frappe.model.document import Document


class CRMGeographyMarketSnapshot(Document):
	def validate(self):
		if self.period_start > self.period_end:
			frappe.throw(_("Period Start must not be after Period End."))
		for fieldname in ("coverage", "confidence"):
			value = float(self.get(fieldname) or 0)
			if not 0 <= value <= 100:
				frappe.throw(_("{0} must be between 0 and 100.").format(fieldname))
		if int(self.market_size or 0) < 0 or int(self.eligible_population or 0) < 0:
			frappe.throw(_("Market population values cannot be negative."))
