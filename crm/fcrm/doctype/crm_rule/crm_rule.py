"""Frappe-managed rule definition and lifecycle boundary."""

from __future__ import annotations

import json

import frappe
from frappe.model.document import Document

from crm.fcrm.rule_engine import normalize_rule_data


class CRMRule(Document):
	def validate(self):
		try:
			data = normalize_rule_data(
				{
					fieldname: self.get(fieldname)
					for fieldname in (
						"rule_id",
						"rule_group",
						"rule_name",
						"description",
						"feature_scope",
						"rule_type",
						"gate_outcome",
						"priority",
						"action",
						"target_actions",
						"condition",
						"status",
						"enabled",
						"revision",
					)
				}
			)
		except ValueError as exc:
			frappe.throw(str(exc), frappe.ValidationError)

		before = self.get_doc_before_save()
		if before and data["rule_id"] != str(before.rule_id or "").strip().upper():
			frappe.throw("CRM Rule ID cannot be changed after creation.", frappe.ValidationError)
		if self.is_new():
			self.name = data["rule_id"]
		status = data["status"]
		lifecycle_change = getattr(frappe.flags, "crm_rule_lifecycle", False)
		publish_change = getattr(frappe.flags, "crm_rule_publish", False)
		if before and data["revision"] != int(before.revision or 0) and not publish_change:
			frappe.throw("CRM Rule revision can only change when publishing.", frappe.PermissionError)
		if before and data["enabled"] != bool(before.enabled) and not lifecycle_change:
			frappe.throw("CRM Rule enabled state must use the lifecycle API.", frappe.PermissionError)
		if (
			before
			and status != str(before.status or "draft").strip().lower()
			and not lifecycle_change
		):
			frappe.throw(
				"CRM Rule lifecycle changes must use the rule admin API.",
				frappe.PermissionError,
			)
		if status == "published" and not data["enabled"]:
			frappe.throw("A published CRM Rule must be enabled.", frappe.ValidationError)
		if status == "published" and not publish_change:
			frappe.throw(
				"Published CRM Rules must be changed through the publish API.",
				frappe.PermissionError,
			)
		if status == "archived" and not getattr(frappe.flags, "crm_rule_archive", False):
			frappe.throw(
				"CRM Rules must be archived through the archive API.", frappe.PermissionError
			)

		self.rule_id = data["rule_id"]
		self.status = status
		self.enabled = int(data["enabled"])
		self.rule_group = data["rule_group"]
		self.rule_name = data["rule_name"]
		self.description = data["description"]
		self.feature_scope = data["feature_scope"]
		self.rule_type = data["rule_type"]
		self.gate_outcome = data["gate_outcome"]
		self.priority = data["priority"]
		self.action = data["action"]
		self.condition = json.dumps(data["condition"], ensure_ascii=False)
		self.target_actions = json.dumps(data["target_actions"], ensure_ascii=False)
		self.revision = data["revision"]
		self.schema_version = data["schema_version"]

	def on_trash(self):
		if self.status != "draft":
			frappe.throw(
				"Only draft CRM Rules can be deleted. Archive published rules instead.",
				frappe.PermissionError,
			)
