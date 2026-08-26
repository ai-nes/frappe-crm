import frappe
from frappe.model.document import Document

from crm.fcrm.student_operational_state import validate_state_transition


class CRMStudentRoutingRequest(Document):
	"""Transactional routing outbox; its pooled ownership identity is immutable."""

	_IDENTITY_FIELDS = ("request_key", "student", "ownership_revision", "pool_revision_key", "campus", "student_pool", "route_trigger", "correlation_token")

	def validate(self):
		validate_state_transition(
			self,
			"student_routing_service",
			{
				"pending": {"leased", "deferred", "applied", "failed", "superseded"},
				"leased": {"pending", "deferred", "applied", "failed", "superseded"},
				"deferred": {"pending", "leased", "failed"},
				"failed": {"pending", "leased"},
			},
		)
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if previous:
			for fieldname in self._IDENTITY_FIELDS:
				if self.get(fieldname) != previous.get(fieldname):
					frappe.throw(f"{fieldname} is immutable on a Student Routing Request")

	def on_trash(self):
		frappe.throw("Student Routing Requests are retained for audit")
