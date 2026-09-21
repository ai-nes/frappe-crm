"""Immutable, evidence-referenced call-quality score for one Interaction revision."""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class CRMNPSPoint(Document):
	"""Prevent edits to an established score outside the settlement service.

	The settlement service may only update the supersession metadata of a prior
	point. Dimension scores, provenance, and attribution are immutable history.
	"""

	def validate(self) -> None:
		if not self.is_new() and not getattr(frappe.flags, "crm_nps_point_service", False):
			previous = self.get_doc_before_save()
			if previous and any(self.get(field) != previous.get(field) for field in self._immutable_fields()):
				frappe.throw("A CRM NPS Point is immutable after settlement.", frappe.PermissionError)

	def on_trash(self) -> None:
		if not getattr(frappe.flags, "crm_nps_point_service", False):
			frappe.throw("A CRM NPS Point cannot be deleted.", frappe.PermissionError)

	@staticmethod
	def _immutable_fields() -> tuple[str, ...]:
		return (
			"interaction",
			"analysis_run",
			"student",
			"sale",
			"sale_user",
			"agent_id",
			"source_revision",
			"source_digest",
			"assessment_digest",
			"idempotency_key",
			"status",
			"satisfaction_score",
			"resolution_score",
			"friction_score",
			"complaint_score",
			"total_score",
			"normalized_score",
			"confidence",
			"evidence_refs",
			"explanation",
			"terminal_reason",
			"policy_revision",
			"model_revision",
			"contract_version",
			"supersedes",
		)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	"""Scope NPS points by both Student visibility and attributed Sale."""
	permission_type = permission_type or ptype
	if permission_type != "read":
		return permission_type == "create" and bool(getattr(frappe.flags, "crm_nps_point_service", False))

	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or "System Manager" in roles:
		return True

	student = doc.get("student")
	if not student:
		return False
	from crm.fcrm.permissions import has_permission as has_student_permission

	if not has_student_permission(frappe.get_doc("CRM Student", student), user=user, ptype="read"):
		return False
	if roles & {"Admissions Director", "Lead Sale", "CRM Manager"}:
		return True

	staff = frappe.db.get_value("CRM Staff", {"user": user, "is_active": 1}, "name")
	return bool(staff and doc.get("sale") == staff)
