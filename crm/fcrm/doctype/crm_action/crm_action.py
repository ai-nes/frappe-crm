import frappe
from frappe.model.document import Document


class CRMAction(Document):
	"""Canonical admissions Action work item and execution evidence aggregate."""

	TERMINAL = {"completed", "cancelled", "superseded", "rejected"}
	TRANSITIONS = {
		"pending": {"accepted", "rejected", "deferred", "superseded", "requires-review"},
		"accepted": {"in-progress", "requires-review", "cancelled", "deferred"},
		"in-progress": {"completed", "requires-review", "cancelled"},
		"requires-review": {"accepted", "in-progress", "cancelled", "superseded"},
		"deferred": {"accepted", "superseded", "requires-review"},
	}

	_PROTECTED = frozenset({
		"student", "state", "action_type", "nba_action", "objective", "disposition", "source_context_revision",
		"policy_context_version", "generation_idempotency_key", "producer_identity",
		"payload_digest", "evidence_references", "action_revision", "current_slot",
		"risk_tier", "package_seed",
		"due_at", "revisit_at", "action_owner", "origin", "contact", "legacy_student_task", "legacy_generic_task",
		"execution_status", "started_at", "outcome_code", "outcome_evidence", "outcome_notes", "linked_interaction", "accepted_at", "completed_at", "terminal_reason",
		"decision_reason", "decision_actor", "decision_at", "decision_revision",
	})

	def validate(self):
		self.worklist_priority_rank = {"high": 0, "medium": 1, "low": 2}.get(self.priority, 99)
		if self.state not in self.TRANSITIONS and self.state not in self.TERMINAL:
			frappe.throw("Invalid CRM Action state.", frappe.ValidationError)
		if self.disposition == "ACT" and not self.action_type:
			frappe.throw("ACT actions require an action type.", frappe.ValidationError)
		if self.disposition != "ACT" and self.action_type:
			frappe.throw("Non-ACT actions cannot carry an action type.", frappe.ValidationError)
		if self.action_type and self.get("nba_action"):
			definition_code = frappe.db.get_value("CRM Action Definition", self.nba_action, "code")
			if definition_code and definition_code != self.action_type:
				frappe.throw("Action Definition does not match action_type.", frappe.ValidationError)
		# Only one non-terminal Action per student may hold the current slot; the
		# database enforces `UNIQUE (student, current_slot)` and NULL never
		# collides, so an empty slot must persist as NULL, not an empty string.
		if not self.current_slot:
			self.current_slot = None
		before = self.get_doc_before_save()
		# The risk tier is a Frappe-owned policy value: a pure function of the
		# action type plus structured, controlled generation signals. It is set on
		# insert and re-derived whenever the generation seed legitimately changes,
		# so a client cannot lower it by editing the draft (the seed is protected).
		seed_changed = not before or before.get("package_seed") != self.get("package_seed")
		type_changed = bool(before) and before.get("action_type") != self.get("action_type")
		if seed_changed or type_changed:
			from crm.fcrm.student_decision import compute_risk_tier

			self.risk_tier = compute_risk_tier(self.action_type, self.get("package_seed"))
		if self.risk_tier not in {"low", "mid", "high"}:
			self.risk_tier = "high"
		# A transition into a terminal state always vacates the current slot in the
		# same write, so a finished Action can never keep occupying the student's
		# single current position.
		entering_terminal = self.state in self.TERMINAL and (not before or before.state != self.state)
		if entering_terminal and self.current_slot:
			self.current_slot = None
		if before and not getattr(frappe.flags, "crm_action_command", False):
			for field in self._PROTECTED:
				if field == "current_slot" and entering_terminal:
					continue
				if before.get(field) != self.get(field):
					frappe.throw("CRM Action fields require a controlled command.", frappe.PermissionError)
		if before and before.state != self.state and self.state not in self.TRANSITIONS.get(before.state, set()):
			frappe.throw(f"Illegal CRM Action transition: {before.state} -> {self.state}", frappe.ValidationError)


def get_permission_query_conditions(user=None):
	from crm.fcrm.permissions import get_permission_query_conditions as student_scope
	user = user or frappe.session.user
	condition = student_scope("CRM Student", user=user)
	return f"`tabCRM Action`.student in (select name from `tabCRM Student` where {condition})" if condition else None


def has_permission(doc, user=None, permission_type=None):
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
