import frappe
from frappe.model.document import Document

from crm.fcrm.action_type_catalog import ACTION_TYPE_CODES, ACTION_TYPE_METADATA, canonicalize_action_type
from crm.fcrm.action_type_registry import is_available_action_type


class CRMActionItem(Document):
	"""Student-scoped work item created from a CRM Action catalog row."""

	TERMINAL = {"completed", "cancelled", "superseded", "rejected"}
	TRANSITIONS = {
		"pending": {"accepted", "rejected", "deferred", "superseded", "requires-review"},
		"accepted": {"in-progress", "requires-review", "cancelled", "deferred"},
		"in-progress": {"completed", "requires-review", "cancelled"},
		"requires-review": {"accepted", "in-progress", "cancelled", "superseded"},
		"deferred": {"accepted", "superseded", "requires-review"},
	}

	_PROTECTED = frozenset({
		"student", "state", "action", "action_type", "nba_action", "objective", "disposition", "source_context_revision",
		"policy_context_version", "generation_idempotency_key", "producer_identity", "payload_digest", "evidence_references",
		"action_revision", "current_slot", "risk_tier", "package_seed", "due_at", "revisit_at", "action_owner", "origin",
		"contact", "legacy_student_task", "legacy_generic_task", "legacy_sales_action", "execution_status", "started_at",
		"source_decision_event", "action_definition_digest",
		"outcome_code", "outcome_evidence", "outcome_notes", "linked_interaction", "accepted_at", "completed_at",
		"terminal_reason", "decision_reason", "decision_actor", "decision_at", "decision_revision",
	})

	def validate(self):
		before = self.get_doc_before_save()
		selected_action = canonicalize_action_type(self.get("action"))
		legacy_action = self.get("action_type")
		if selected_action:
			if not is_available_action_type(selected_action):
				frappe.throw("Unsupported CRM Action.", frappe.ValidationError)
			self.action = selected_action
			self.action_type = ACTION_TYPE_METADATA[selected_action]["category"]
		elif legacy_action in ACTION_TYPE_CODES and not is_available_action_type(legacy_action):
			if not before or before.get("action_type") != legacy_action:
				frappe.throw("Unsupported legacy CRM Action.", frappe.ValidationError)
		self.worklist_priority_rank = {"high": 0, "medium": 1, "low": 2}.get(self.priority, 99)
		if self.state not in self.TRANSITIONS and self.state not in self.TERMINAL:
			frappe.throw("Invalid CRM Action Item state.", frappe.ValidationError)
		if self.disposition == "ACT" and not (self.action or legacy_action):
			frappe.throw("ACT items require a CRM Action.", frappe.ValidationError)
		if self.disposition != "ACT" and self.action:
			frappe.throw("Non-ACT items cannot carry a CRM Action.", frappe.ValidationError)
		seed_changed = not before or before.get("package_seed") != self.get("package_seed")
		type_changed = bool(before) and (before.get("action") != self.get("action") or before.get("action_type") != self.get("action_type"))
		if seed_changed or type_changed:
			from crm.fcrm.student_decision import compute_risk_tier

			self.risk_tier = compute_risk_tier(self.action or legacy_action, self.get("package_seed"))
		if self.risk_tier not in {"low", "mid", "high"}:
			self.risk_tier = "high"
		entering_terminal = self.state in self.TERMINAL and (not before or before.state != self.state)
		if entering_terminal and self.current_slot:
			self.current_slot = None
		if before and not getattr(frappe.flags, "crm_action_command", False):
			for field in self._PROTECTED:
				if field == "current_slot" and entering_terminal:
					continue
				if before.get(field) != self.get(field):
					frappe.throw("CRM Action Item fields require a controlled command.", frappe.PermissionError)
		if before and before.state != self.state and self.state not in self.TRANSITIONS.get(before.state, set()):
			frappe.throw(f"Illegal CRM Action Item transition: {before.state} -> {self.state}", frappe.ValidationError)


def get_permission_query_conditions(user=None):
	from crm.fcrm.permissions import get_permission_query_conditions as student_scope
	user = user or frappe.session.user
	condition = student_scope("CRM Student", user=user)
	return f"`tabCRM Action Item`.student in (select name from `tabCRM Student` where {condition})" if condition else None


def has_permission(doc, user=None, permission_type=None, ptype=None):
	permission_type = permission_type or ptype
	if permission_type == "create" and not getattr(doc, "name", None):
		return True
	student = doc.get("student") if isinstance(doc, dict) else getattr(doc, "student", None)
	if not student:
		return False
	from crm.fcrm.permissions import get_permission_query_conditions as student_scope
	condition = student_scope("CRM Student", user=user or frappe.session.user)
	if condition is None:
		return True
	return bool(frappe.db.sql(
		"select name from `tabCRM Student` where name = %s and (" + condition + ") limit 1", (student,)
	))
