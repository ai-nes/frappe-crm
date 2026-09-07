import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.permissions import (
	get_permission_query_conditions as get_student_permission_query_conditions,
)
from crm.fcrm.permissions import (
	has_permission as has_student_permission,
)

# Fields that are sealed once a recommendation is bound to an NBA Evaluation.
_EVALUATION_FROZEN_FIELDS = ("evaluation", "ai_payload", "recommendation_key", "rank", "action")


def _normalized(value):
	return None if value in (None, "") else value


def _parsed_explanation(value):
	"""Normalize ``explanation`` (raw JSON text or an already-parsed dict) for comparison."""
	if not value:
		return None
	if isinstance(value, str):
		try:
			return frappe.parse_json(value)
		except Exception:
			return value
	return value


class CRMRecommendation(Document):
	"""A recommendation addressed to one typed target and one action catalog row."""

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
		self._guard_evaluation_epoch_uniqueness()
		self._guard_evaluation_epoch_immutability()
		self._guard_explanation_write_once()

	def _guard_explanation_write_once(self):
		"""Seal ``explanation`` once it holds a real structured object.

		Setting it from empty to a value is allowed exactly once, regardless of
		whether the row is evaluation-scoped; changing an already-set
		explanation to a different value is rejected. A no-op save (unchanged
		or still empty) always passes. A freshly assigned ``explanation`` may be
		a Python dict while the value reloaded from the database is its JSON
		text, so both sides are parsed to a comparable Python object first.
		"""
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if not before:
			return
		previous = _parsed_explanation(before.get("explanation"))
		current = _parsed_explanation(self.explanation)
		if previous and current != previous:
			frappe.throw(
				_("Recommendation explanation is already set and cannot change."),
				frappe.ValidationError,
			)

	def _guard_evaluation_epoch_uniqueness(self):
		"""One evaluation may hold at most one row per kernel recommendation key.

		Legacy rows (no linked evaluation) are exempt: the pair is only meaningful
		once both sides are set.
		"""
		if not self.evaluation or not self.recommendation_key:
			return
		clash = frappe.db.exists(
			"CRM Recommendation",
			{
				"evaluation": self.evaluation,
				"recommendation_key": self.recommendation_key,
				"name": ["!=", self.name or ""],
			},
		)
		if clash:
			frappe.throw(
				_("This evaluation already has a recommendation for that key."),
				frappe.ValidationError,
			)

	def _guard_evaluation_epoch_immutability(self):
		"""Seal the kernel-owned fields once the row is bound to an evaluation.

		The evaluation epoch treats a persisted recommendation as an immutable
		record of what the engine emitted. Legacy rows -- those never bound to an
		evaluation -- keep their existing mutable status projection.
		"""
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if not before or not before.get("evaluation"):
			return
		changed = [
			field
			for field in _EVALUATION_FROZEN_FIELDS
			if _normalized(self.get(field)) != _normalized(before.get(field))
		]
		if changed:
			frappe.throw(
				_("An evaluation-scoped recommendation is immutable: {0} cannot change.").format(
					", ".join(changed)
				),
				frappe.ValidationError,
			)


def get_permission_query_conditions(user=None):
	"""Scope Student-targeted recommendations through the Student policy."""
	if not user:
		user = frappe.session.user
	student_condition = get_student_permission_query_conditions("CRM Lead", user=user)
	if student_condition is None:
		return None
	if student_condition == "1=0":
		return "1=0"
	recommendation_table = chr(96) + "tabCRM Recommendation" + chr(96)
	student_table = chr(96) + "tabCRM Lead" + chr(96)
	return (
		f"{recommendation_table}.target_type = 'CRM Lead' AND "
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
	if target_type != "CRM Lead" or not target_id:
		return False
	try:
		student_doc = frappe.get_doc("CRM Lead", target_id)
		return has_student_permission(student_doc, user=user, permission_type=permission_type)
	except Exception:
		return False
