import json

import frappe
from frappe.model.document import Document

from crm.fcrm.nba_canonical import canonical_digest, json_string_list
from crm.fcrm.nba_policy import (
	decision_policy_digest_payload,
	validate_decision_policy_numbers,
	validate_diversity_rule,
	validate_score_weights,
	kernel_policy_snapshot,
)


class CRMNBADecisionPolicy(Document):
	"""Aggregate of the knobs that shape NBA ranking and recommendation output.

	One row per ``policy_key`` may be active at a time; the admin activates and
	deactivates explicitly. ``policy_revision`` bumps whenever a digested knob
	changes so a produced evaluation can pin the exact policy it ran under.
	"""

	def validate(self):
		try:
			validate_decision_policy_numbers(self.top_n, self.max_recommendations, self.min_score_threshold)
			weights = validate_score_weights(self.score_weights)
			conflict_fields = json_string_list(self.conflict_key_fields)
			self.diversity_rule = validate_diversity_rule(self.diversity_rule)
		except ValueError as exc:
			frappe.throw(str(exc), frappe.ValidationError)

		# Frappe rejects a raw list assigned to a JSON field; store canonical text.
		self.score_weights = json.dumps(weights, sort_keys=True) if weights else None
		self.conflict_key_fields = json.dumps(conflict_fields) if conflict_fields else None

		if self.is_active:
			clash = frappe.db.exists(
				"CRM NBA Decision Policy",
				{
					"policy_key": self.policy_key,
					"is_active": 1,
					"name": ["!=", self.name or ""],
				},
			)
			if clash:
				frappe.throw(
					f"Another active NBA Decision Policy already exists for '{self.policy_key}'. "
					"Deactivate it before activating this one.",
					frappe.ValidationError,
				)

		if self.kernel_policy:
			try:
				digest = canonical_digest(kernel_policy_snapshot({"kernel_policy": self.kernel_policy}))
			except ValueError as exc:
				frappe.throw(str(exc), frappe.ValidationError)
		else:
			digest = canonical_digest(
				decision_policy_digest_payload(
					{
						"top_n": self.top_n,
						"max_recommendations": self.max_recommendations,
						"min_score_threshold": self.min_score_threshold,
						"score_weights": weights,
						"conflict_key_fields": conflict_fields,
						"diversity_rule": self.diversity_rule,
					}
				)
			)
		if digest != (self.policy_digest or ""):
			self.policy_digest = digest
			self.policy_revision = (
				int(self.policy_revision or 0) + 1 if not self.is_new() else int(self.policy_revision or 1)
			)
