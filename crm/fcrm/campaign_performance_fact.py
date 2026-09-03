"""Canonical, idempotent writer for campaign performance observations."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import frappe
from frappe import _

from crm.fcrm.campaign_contracts import (
	canonical_dimension_key,
	performance_fact_fingerprint,
	validate_observed_measures,
)


@contextmanager
def _writer_context():
	previous = getattr(frappe.flags, "campaign_performance_fact_writer", False)
	frappe.flags.campaign_performance_fact_writer = True
	try:
		yield
	finally:
		frappe.flags.campaign_performance_fact_writer = previous


def record_performance_fact(
	*,
	campaign: str,
	channel_assignment: str,
	period_start: str,
	period_end: str,
	timezone: str,
	source_system: str,
	ingestion_run: str,
	source_key: str,
	dimension_values: dict[str, Any],
	measures: dict[str, Any] | None = None,
	revision: int = 1,
	supersedes: str | None = None,
	correction_reference: str | None = None,
) -> dict[str, Any]:
	"""Insert one atomic fact or return its exact prior result on replay."""

	if not campaign or not channel_assignment or not dimension_values:
		frappe.throw(_("Campaign, Channel Assignment and dimensions are required."), frappe.ValidationError)
	if not all(
		str(value or "").strip()
		for value in (period_start, period_end, timezone, source_system, ingestion_run, source_key)
	):
		frappe.throw(_("Period, timezone, source and source key are required."), frappe.ValidationError)
	try:
		dimension_key = canonical_dimension_key(dimension_values)
		observed = validate_observed_measures(measures or {})
		fingerprint = performance_fact_fingerprint(
			source_system=source_system, ingestion_run=ingestion_run, source_key=source_key
		)
	except ValueError as exc:
		frappe.throw(str(exc), frappe.ValidationError)
	existing = frappe.db.get_value(
		"CRM Campaign Performance Fact",
		{"idempotency_fingerprint": fingerprint},
		["name", "fact_key"],
		as_dict=True,
	)
	if existing:
		return {"fact": existing.name, "fact_key": existing.fact_key, "replayed": True, "revision": revision}
	assignment = frappe.db.get_value(
		"CRM Campaign Channel Assignment",
		channel_assignment,
		["campaign", "is_active", "effective_from", "effective_until"],
		as_dict=True,
	)
	if not assignment:
		frappe.throw(_("Channel Assignment does not exist."), frappe.DoesNotExistError)
	if assignment.campaign != campaign:
		frappe.throw(_("Channel Assignment must belong to the selected Campaign."), frappe.ValidationError)
	if not assignment.is_active:
		frappe.throw(_("Channel Assignment is not active."), frappe.ValidationError)
	if assignment.effective_from and str(period_start) < str(assignment.effective_from):
		frappe.throw(
			_("Performance period precedes the Channel Assignment effective date."), frappe.ValidationError
		)
	if assignment.effective_until and str(period_end) > str(assignment.effective_until):
		frappe.throw(
			_("Performance period follows the Channel Assignment effective date."), frappe.ValidationError
		)
	if int(revision) > 1 and not supersedes:
		frappe.throw(_("A correction revision requires supersedes."), frappe.ValidationError)
	if supersedes:
		prior = frappe.db.get_value(
			"CRM Campaign Performance Fact",
			supersedes,
			[
				"campaign",
				"channel_assignment",
				"period_start",
				"period_end",
				"timezone",
				"normalized_dimension",
				"revision",
			],
			as_dict=True,
		)
		if (
			not prior
			or any(
				prior.get(fieldname) != expected
				for fieldname, expected in {
					"campaign": campaign,
					"channel_assignment": channel_assignment,
					"period_start": period_start,
					"period_end": period_end,
					"timezone": timezone,
					"normalized_dimension": dimension_key,
				}.items()
			)
			or int(revision) != int(prior.revision) + 1
		):
			frappe.throw(
				_("Correction must supersede the immediately preceding fact grain."), frappe.ValidationError
			)
	values = {
		"doctype": "CRM Campaign Performance Fact",
		"fact_key": "|".join((campaign, channel_assignment, str(period_start), str(period_end), dimension_key, str(revision))),
		"campaign": campaign,
		"channel_assignment": channel_assignment,
		"normalized_dimension": dimension_key,
		"dimension_values": dimension_values,
		"period_start": period_start,
		"period_end": period_end,
		"timezone": timezone,
		"source_system": source_system,
		"ingestion_run": ingestion_run,
		**observed,
		"raw_measures": measures or {},
		"revision": int(revision),
		"supersedes": supersedes,
		"source_reference": correction_reference or f"{source_system}:{ingestion_run}:{source_key}",
		"idempotency_fingerprint": fingerprint,
	}
	with _writer_context():
		try:
			doc = frappe.get_doc(values).insert(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			existing = frappe.db.get_value(
				"CRM Campaign Performance Fact",
				{"idempotency_fingerprint": fingerprint},
				["name", "fact_key"],
				as_dict=True,
			)
			if not existing:
				raise
			return {
				"fact": existing.name,
				"fact_key": existing.fact_key,
				"replayed": True,
				"revision": revision,
			}
	return {"fact": doc.name, "fact_key": doc.fact_key, "replayed": False, "revision": doc.revision}
