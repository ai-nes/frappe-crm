"""Public boundary for canonical campaign performance ingestion."""

from __future__ import annotations

import json

import frappe

from crm.fcrm.campaign_performance_fact import record_performance_fact


@frappe.whitelist()
def record(
	campaign: str,
	channel_assignment: str,
	period_start: str,
	period_end: str,
	timezone: str,
	source_system: str,
	ingestion_run: str,
	source_key: str,
	dimension_values=None,
	measures=None,
	revision: int = 1,
	supersedes: str | None = None,
	correction_reference: str | None = None,
):
	if isinstance(dimension_values, str):
		dimension_values = json.loads(dimension_values)
	if isinstance(measures, str):
		measures = json.loads(measures)
	return record_performance_fact(
		campaign=campaign,
		channel_assignment=channel_assignment,
		period_start=period_start,
		period_end=period_end,
		timezone=timezone,
		source_system=source_system,
		ingestion_run=ingestion_run,
		source_key=source_key,
		dimension_values=dimension_values or {},
		measures=measures or {},
		revision=int(revision),
		supersedes=supersedes,
		correction_reference=correction_reference,
	)
