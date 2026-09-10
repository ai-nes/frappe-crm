"""Frappe-managed version boundary for the CRM Rule registry."""

from __future__ import annotations

import frappe
from frappe.model.document import Document

from crm.fcrm.rule_engine import normalize_rule_version_data


class CRMRuleVersion(Document):
	def validate(self):
		try:
			data = normalize_rule_version_data(
				{
					fieldname: self.get(fieldname)
					for fieldname in (
						"version_id",
						"version_name",
						"description",
						"status",
						"is_active",
						"revision",
					)
				}
			)
		except ValueError as exc:
			frappe.throw(str(exc), frappe.ValidationError)

		before = self.get_doc_before_save()
		if before and data["version_id"] != str(before.version_id or "").strip().upper():
			frappe.throw("CRM Rule Version ID cannot be changed after creation.", frappe.ValidationError)
		if self.is_new():
			if data["status"] != "draft" or data["is_active"] or data["revision"]:
				frappe.throw("A new CRM Rule Version must start as an inactive draft.", frappe.ValidationError)
			self.name = data["version_id"]

		lifecycle_change = getattr(frappe.flags, "crm_rule_version_lifecycle", False)
		if before and data["status"] != str(before.status or "draft").strip().lower() and not lifecycle_change:
			frappe.throw(
				"CRM Rule Version lifecycle changes must use the version admin API.",
				frappe.PermissionError,
			)
		if before and data["is_active"] != bool(before.is_active) and not lifecycle_change:
			frappe.throw(
				"CRM Rule Version active state must use the version admin API.",
				frappe.PermissionError,
			)
		if before and str(before.status or "draft").lower() in {"published", "archived"}:
			changed = any(
				before.get(fieldname) != self.get(fieldname)
				for fieldname in ("version_name", "description")
			)
			if changed and not lifecycle_change:
				frappe.throw(
					"Published or archived CRM Rule Versions are immutable. Clone them to edit.",
					frappe.PermissionError,
				)

		self.version_id = data["version_id"]
		self.version_name = data["version_name"]
		self.description = data["description"]
		self.status = data["status"]
		self.is_active = int(data["is_active"])
		self.revision = data["revision"]
		self.schema_version = data["schema_version"]

	def on_trash(self):
		if self.status != "draft" or self.is_active:
			frappe.throw(
				"Only inactive draft CRM Rule Versions can be deleted. Archive published versions instead.",
				frappe.PermissionError,
			)
