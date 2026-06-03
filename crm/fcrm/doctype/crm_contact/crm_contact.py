import frappe
from frappe.model.document import Document

from crm.fcrm.doctype.crm_service_level_agreement.utils import get_sla


class CRMContact(Document):
	def validate(self):
		self.apply_sla()

	def apply_sla(self):
		if not self.communication_status:
			self.communication_status = "Open"

		sla = get_sla(self)
		if not sla:
			self.sla = None
			return

		self.sla = sla.name
		frappe.get_doc("CRM Service Level Agreement", sla.name).apply(self)


def get_permission_query_conditions(user=None):
	if not user:
		user = frappe.session.user

	if "System Manager" in frappe.get_roles(user) or "CRM Manager" in frappe.get_roles(user):
		return None

	staff_name = frappe.db.get_value("Staff", {"user": user}, "name")
	if not staff_name:
		return "1=0"

	campus = frappe.db.get_value("Staff", staff_name, "campus")
	if not campus:
		return "1=0"

	staff_in_campus = frappe.db.get_all(
		"Staff",
		filters={"campus": campus},
		pluck="name",
	)

	if not staff_in_campus:
		return "1=0"

	escaped = ", ".join(frappe.db.escape(s) for s in staff_in_campus)
	return f"`tabCRM Contact`.assigned_to in ({escaped})"
