import frappe
from frappe.model.document import Document


class CRMInteraction(Document):
	def before_validate(self):
		if not self.interaction_datetime:
			self.interaction_datetime = frappe.utils.now_datetime()
		if not self.actor:
			self.actor = frappe.session.user

	def validate(self):
		if not self.student and not self.crm_contact:
			frappe.throw(frappe._("An interaction must be linked to a Student or a CRM Contact."))
		previous = self.get_doc_before_save() if not self.is_new() else None
		if ((self.source_verified and not previous) or (previous and bool(self.source_verified) != bool(previous.source_verified))) and not getattr(frappe.flags, "student_sla_source_service", False):
			frappe.throw(frappe._("Only the interaction source service may verify provenance."))
		if self.sla_response_sealed and not getattr(frappe.flags, "student_sla_response_service", False):
			frappe.throw(frappe._("An SLA response interaction is immutable."))
		if previous and previous.sla_response_sealed and not getattr(frappe.flags, "student_sla_response_service", False):
			frappe.throw(frappe._("An SLA response interaction is immutable."))
		if previous and previous.source_verified:
			for fieldname in ("student", "reference_doctype", "reference_docname"):
				if self.get(fieldname) != previous.get(fieldname):
					frappe.throw(frappe._("A verified interaction source is immutable."))

	def on_update(self):
		student = self.student or frappe.db.get_value("CRM Contact", self.crm_contact, "student")
		if student:
			from crm.services.student_context import mark_student_context_changed

			mark_student_context_changed(student, "interaction_material_change")

	@staticmethod
	def default_list_data():
		columns = [
			{
				"label": "Student",
				"type": "Link",
				"key": "student",
				"options": "CRM Student",
				"width": "14rem",
			},
			{
				"label": "Contact",
				"type": "Link",
				"key": "crm_contact",
				"options": "CRM Contact",
				"width": "14rem",
			},
			{
				"label": "Interaction Type",
				"type": "Link",
				"key": "interaction_type",
				"options": "CRM Interaction Type",
				"width": "12rem",
			},
			{
				"label": "Interaction Time",
				"type": "Datetime",
				"key": "interaction_datetime",
				"width": "12rem",
			},
			{"label": "Outcome", "type": "Select", "key": "outcome", "width": "10rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = [
			"name",
			"student",
			"crm_contact",
			"interaction_type",
			"interaction_datetime",
			"summary",
			"outcome",
			"modified",
		]
		return {"columns": columns, "rows": rows}
