from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.admissions_canonical_contracts import validate_fact_envelope


class CRMCampaignPerformanceFact(Document):
	_IMMUTABLE_FIELDS = (
		"campaign",
		"channel_assignment",
		"normalized_dimension",
		"dimension_values",
		"period_start",
		"period_end",
		"timezone",
		"source_system",
		"ingestion_run",
		"spend",
		"impressions",
		"clicks",
		"leads",
		"applications",
		"enrolled",
		"raw_measures",
		"recorded_at",
		"revision",
		"supersedes",
		"idempotency_fingerprint",
	)

	def before_insert(self):
		if not getattr(frappe.flags, "campaign_performance_fact_writer", False):
			frappe.throw(
				_("Performance Facts may only be written by the canonical ingestion command."),
				frappe.PermissionError,
			)

	def before_validate(self):
		if not self.recorded_at:
			self.recorded_at = frappe.utils.now_datetime()
		if not self.revision:
			self.revision = 1
		if not self.schema_version:
			self.schema_version = "admissions-erd-v2"
		if (
			self.campaign
			and self.channel_assignment
			and self.period_start
			and self.period_end
			and self.normalized_dimension
			and not self.fact_key
		):
			self.fact_key = "|".join(
				(
					self.campaign,
					self.channel_assignment,
					str(self.period_start),
					str(self.period_end),
					self.normalized_dimension,
					str(self.revision),
				)
			)

	def validate(self):
		validate_fact_envelope(self.as_dict())
		for fieldname in ("spend", "impressions", "clicks", "leads", "applications", "enrolled"):
			if float(self.get(fieldname) or 0) < 0:
				frappe.throw(_("{0} cannot be negative.").format(fieldname), frappe.ValidationError)
		if not self.is_new():
			previous = self.get_doc_before_save()
			if previous and any(
				self.get(fieldname) != previous.get(fieldname) for fieldname in self._IMMUTABLE_FIELDS
			):
				frappe.throw(
					_("Performance facts are immutable; write a correction with supersedes."),
					frappe.PermissionError,
				)

	def on_trash(self):
		frappe.throw(_("Performance facts are append-only."), frappe.PermissionError)
