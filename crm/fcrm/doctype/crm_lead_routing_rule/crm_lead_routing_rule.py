import frappe
from frappe.model.document import Document


class CRMLeadRoutingRule(Document):
	def validate(self):
		school_filter = ("in", ["", None]) if not self.school else self.school
		filters = {
			"branch": self.branch,
			"province": self.province,
			"school": school_filter,
			"name": ("!=", self.name),
		}
		existing = frappe.db.get_value("CRM Lead Routing Rule", filters, "name")
		if existing:
			scope = f"branch='{self.branch}', province='{self.province}'"
			if self.school:
				scope += f", school='{self.school}'"
			frappe.throw(f"Routing rule already exists for {scope}: {existing}")
