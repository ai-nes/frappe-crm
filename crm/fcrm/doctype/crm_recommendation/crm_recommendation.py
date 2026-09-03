import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.permissions import (
	get_permission_query_conditions as get_student_permission_query_conditions,
)
from crm.fcrm.permissions import (
	has_permission as has_student_permission,
)


class CRMRecommendation(Document):
	"""A recommendation addressed to one typed target and one action definition."""

	def validate(self):
		if not self.recommendation_id:
			frappe.throw(_("Recommendation ID is required."), frappe.ValidationError)
		if not self.target_type or not self.target_id:
			frappe.throw(_("Target type and target ID are required."), frappe.ValidationError)
		if self.priority not in {"high", "medium", "low"}:
			frappe.throw(_("Invalid recommendation priority."), frappe.ValidationError)
		if self.confidence not in (None, "") and not 0 <= float(self.confidence) <= 1:
			frappe.throw(_("Confidence must be between 0 and 1."), frappe.ValidationError)
		if self.expected_impact not in (None, "") and not -1 <= float(self.expected_impact) <= 1:
			frappe.throw(_("Expected impact must be between -1 and 1."), frappe.ValidationError)


def get_permission_query_conditions(user=None):
	"""Scope Student-targeted recommendations through the Student policy."""
	if not user:
		user = frappe.session.user
	student_condition = get_student_permission_query_conditions("CRM Student", user=user)
	if student_condition is None:
		return None
	if student_condition == "1=0":
		return "1=0"
	recommendation_table = chr(96) + "tabCRM Recommendation" + chr(96)
	student_table = chr(96) + "tabCRM Student" + chr(96)
	return (
		f"{recommendation_table}.target_type = 'CRM Student' AND "
		f"{recommendation_table}.target_id in ("
		f"select {student_table}.name from {student_table} "
		f"where ({student_condition}))"
	)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	"""Apply the same target-derived scope to direct document reads."""
	permission_type = permission_type or ptype
	if permission_type == "create" and not getattr(doc, "name", None):
		return True
	if not user:
		user = frappe.session.user
	target_type = doc.get("target_type") if isinstance(doc, dict) else getattr(doc, "target_type", None)
	target_id = doc.get("target_id") if isinstance(doc, dict) else getattr(doc, "target_id", None)
	if target_type != "CRM Student" or not target_id:
		return False
	try:
		student_doc = frappe.get_doc("CRM Student", target_id)
		return has_student_permission(student_doc, user=user, permission_type=permission_type)
	except Exception:
		return False
