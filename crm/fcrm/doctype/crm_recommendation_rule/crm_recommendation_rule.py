import json

import frappe
from frappe.model.document import Document

from crm.fcrm.recommendation_rule_constraints import (
	normalize_conditions,
	normalize_stop_conditions,
	validate_rule_settings,
)


class CRMRecommendationRule(Document):
	def validate(self):
		if not self.rule_key or not self.rule_key.strip():
			frappe.throw("Recommendation Rule key is required.", frappe.ValidationError)
		if not self.display_name or not self.display_name.strip():
			frappe.throw("Recommendation Rule display name is required.", frappe.ValidationError)
		if self.status not in {"draft", "published", "archived"}:
			frappe.throw("Recommendation Rule status is invalid.", frappe.ValidationError)
		before = self.get_doc_before_save()
		if (
			before
			and self.status != before.status
			and not getattr(frappe.flags, "recommendation_rule_lifecycle", False)
		):
			frappe.throw(
				"Recommendation Rule lifecycle changes must use the admin API.",
				frappe.PermissionError,
			)
		try:
			validate_rule_settings(
				self.trigger_type,
				self.trigger_event,
				self.priority,
				self.cooldown_value,
				self.cooldown_unit,
				self.max_occurrences,
				self.expires_after_hours,
			)
		except ValueError as exc:
			frappe.throw(str(exc), frappe.ValidationError)
		if self.status == "published" and not self.enabled:
			frappe.throw("A published Recommendation Rule must be enabled.", frappe.ValidationError)
		if self.status == "published" and not getattr(frappe.flags, "recommendation_rule_publish", False):
			frappe.throw(
				"Published Recommendation Rules must be changed through the publish API.",
				frappe.PermissionError,
			)
		if self.status == "archived" and not getattr(frappe.flags, "recommendation_rule_archive", False):
			frappe.throw(
				"Recommendation Rules must be archived through the archive API.",
				frappe.PermissionError,
			)
		try:
			self.conditions = json.dumps(normalize_conditions(self.conditions), ensure_ascii=False)
			self.stop_conditions = json.dumps(
				normalize_stop_conditions(self.stop_conditions), ensure_ascii=False
			)
		except ValueError as exc:
			frappe.throw(str(exc), frappe.ValidationError)

	def on_trash(self):
		if self.status != "draft":
			frappe.throw(
				"Only draft Recommendation Rules can be deleted. Archive published Rules instead.",
				frappe.PermissionError,
			)
