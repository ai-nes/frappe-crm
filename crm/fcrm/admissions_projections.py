"""Pure response helpers for the server-owned admissions projection DTOs."""

from __future__ import annotations

from typing import Any

from crm.fcrm.admissions_contracts import CONTRACT_VERSION, LIFECYCLE_MAPPING_VERSION, normalize_filters


def build_projection(
	name: str,
	filters: dict[str, Any] | None = None,
	data: dict[str, Any] | None = None,
	*,
	source_mode: str = "target",
	source_status: str = "ready",
	warnings: list[str] | None = None,
	ai_unavailable: bool = False,
	definition_version: str | None = None,
	subject_grain: str | None = None,
	stale: bool = False,
) -> dict[str, Any]:
	"""Build the stable envelope shared by PH-01, PH-04, and PH-05."""

	return {
		"contract": CONTRACT_VERSION,
		"projection": name,
		"filters": normalize_filters(filters),
		"source": {
			"mode": source_mode,
			"status": source_status,
			"mapping_version": LIFECYCLE_MAPPING_VERSION,
			"definition_version": definition_version or CONTRACT_VERSION,
			"subject_grain": subject_grain,
			"stale": stale,
		},
		"data": data or {},
		"warnings": warnings or [],
		"ai_unavailable": ai_unavailable,
		"stale": stale,
	}
