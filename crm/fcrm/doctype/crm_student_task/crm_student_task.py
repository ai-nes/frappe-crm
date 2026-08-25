import frappe
from frappe.model.document import Document


class CRMStudentTask(Document):
	"""Single current-slot owner for Recommendation v2."""

	_PROTECTED_FIELDS = frozenset(
		{
			"student",
			"current_slot",
			"source_context_revision",
			"disposition",
			"action_type",
			"objective",
			"policy_version",
			"context_version",
			"generation_idempotency_key",
			"producer_identity",
			"payload_digest",
			"recommendation",
			"sales_action",
			"evidence_references",
			"package_seed",
			"state",
			"requires_review",
			"review_revision",
			"action_revision",
			"execution_package_version",
			"outcome",
		}
	)

	def validate(self):
		before = self.get_doc_before_save()
		if before and not getattr(frappe.flags, "student_task_command", False):
			for field in self._PROTECTED_FIELDS:
				if before.get(field) != self.get(field):
					frappe.throw(
						"Student Task fields can only be changed by controlled commands.",
						frappe.PermissionError,
					)
		if self.current_slot and self.current_slot != "CURRENT":
			raise ValueError("current_slot must be CURRENT or empty")
		if self.disposition == "ACT" and not self.action_type:
			raise ValueError("ACT task requires action_type")
		if self.disposition != "ACT" and self.action_type:
			raise ValueError("MONITOR/NURTURE task cannot carry action_type")


def get_permission_query_conditions(user=None):
	from crm.fcrm.permissions import get_permission_query_conditions as student_scope

	if not user:
		user = frappe.session.user
	condition = student_scope("CRM Student", user=user)
	return (
		f"`tabCRM Student Task`.student in (select `tabCRM Student`.name from `tabCRM Student` where {condition})"
		if condition
		else None
	)


def has_permission(doc, user=None, permission_type=None):
	if not user:
		user = frappe.session.user
	student = doc.get("student") if isinstance(doc, dict) else getattr(doc, "student", None)
	if not student:
		return False
	from crm.fcrm.permissions import get_permission_query_conditions as student_scope

	condition = student_scope("CRM Student", user=user)
	if condition is None:
		return True
	return bool(
		frappe.db.sql(
			"select name from `tabCRM Student` where name = %s and (" + condition + ") limit 1", (student,)
		)
	)
