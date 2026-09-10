from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.admissions_canonical_contracts import normalize_planning_scope
from crm.fcrm.admissions_migration import stable_fingerprint


class CRMPlanningScope(Document):
	def _scope_values(self):
		return {
			fieldname: self.get(fieldname)
			for fieldname in ("region", "territory", "province", "team", "campus", "major", "scope_key")
		}

	def before_validate(self):
		if not self.schema_version:
			self.schema_version = "admissions-erd"
		if self.effective_from and self.effective_until and self.effective_from > self.effective_until:
			frappe.throw(_("Effective Until must not be before Effective From."), frappe.ValidationError)
		values = self._scope_values()
		try:
			normalized = normalize_planning_scope(values)
		except ValueError:
			return
		self.scope_key = normalized["scope_key"]
		if not self.idempotency_fingerprint:
			self.idempotency_fingerprint = stable_fingerprint(
				"planning-scope",
				self.scope_key,
				self.effective_from,
				self.effective_until,
				self.status,
			)

	def validate(self):
		normalized = normalize_planning_scope(self._scope_values())
		if self.scope_key != normalized["scope_key"]:
			frappe.throw(_("Scope Key must match the selected planning Links."), frappe.ValidationError)
		if self.effective_from > self.effective_until:
			frappe.throw(_("Effective Until must not be before Effective From."), frappe.ValidationError)
		if self.status == "Approved" and self.territory and not self._has_effective_territory_assignment():
			frappe.throw(
				_("An approved territory scope requires an effective geography assignment."),
				frappe.ValidationError,
			)

	def _has_effective_territory_assignment(self):
		if not frappe.db.exists("DocType", "CRM Territory Geography Assignment"):
			return False
		rows = frappe.get_all(
			"CRM Territory Geography Assignment",
			filters={"territory": self.territory, "status": "Active"},
			fields=["effective_from", "effective_until"],
			limit_page_length=0,
		)
		return any(
			str(row.effective_from) <= str(self.effective_from)
			and str(row.effective_until) >= str(self.effective_until)
			for row in rows
		)
