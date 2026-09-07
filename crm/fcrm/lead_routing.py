"""Canonical routing entrypoints for the pre-conversion CRM Lead.

Lead creation is intentionally passive.  Assignment is an explicit operation
owned by the batch command, which delegates the actual selection and ownership
write to the existing zone/capacity service.
"""

from __future__ import annotations

from typing import Any


def route_lead_now(
	lead: str | Any,
	*,
	trigger: str = "manual_batch",
	expected_revision: int | None = None,
	correlation_id: str | None = None,
) -> dict[str, Any]:
	"""Run the canonical routing service for one persisted Lead.

	The imported service still has Student-oriented names for compatibility, but
	its persisted routing target is now ``CRM Lead``.  Keeping this boundary in a
	small Lead-facing module prevents new callers from reaching the legacy
	campus-only router or duplicating ownership logic.
	"""
	from crm.fcrm.student_routing import route_pool_owned_student

	lead_name = str(getattr(lead, "name", lead) or "").strip()
	if not lead_name:
		raise ValueError("lead is required")
	return route_pool_owned_student(
		lead_name,
		trigger=trigger,
		expected_revision=expected_revision,
		correlation_id=correlation_id,
	)
