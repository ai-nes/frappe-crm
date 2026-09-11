# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Durable aggregate for one NBA Evaluation run.

The row is service-written and read-only in the desk. Its lifecycle -- request,
claim, snapshot, settle, reconcile -- is owned by ``crm.fcrm.nba_evaluations``;
the compare-and-swap fences there operate through ``frappe.db.sql`` and bypass
this controller, so validation here is limited to shape guards for the rare
direct write.
"""

from frappe.model.document import Document

from crm.fcrm.decision_trace import validate_rule_decision, validate_trace_entries


class CRMNBAEvaluation(Document):
	def validate(self):
		if self.terminal_reason and len(self.terminal_reason) > 500:
			from frappe import ValidationError, throw

			throw("NBA Evaluation terminal reason is bounded to 500 characters.", ValidationError)
		if self.recommendation_count is not None and int(self.recommendation_count) < 0:
			from frappe import ValidationError, throw

			throw("NBA Evaluation recommendation count cannot be negative.", ValidationError)
		try:
			if self.evaluation_trace:
				validate_trace_entries(self.evaluation_trace)
			if self.rule_decision:
				decision = validate_rule_decision(self.rule_decision)
				identity = {
					"rule_version": self.get("rule_version"),
					"rule_version_digest": self.get("rule_version_digest"),
					"ruleset_digest": self.get("ruleset_digest"),
				}
				if any(decision[field] != identity[field] for field in identity):
					raise ValueError("NBA Evaluation rule decision identity is inconsistent.")
		except ValueError as exc:
			from frappe import ValidationError, throw

			throw(str(exc), ValidationError)
