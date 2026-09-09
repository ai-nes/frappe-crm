"""Pure backfill decisions for legacy Student → Application conversion."""

from __future__ import annotations

from typing import Any

from crm.fcrm.admissions_canonical_contracts import canonical_attempt_key
from crm.fcrm.admissions_migration import provenance


def application_backfill_decision(
	student: dict[str, Any],
	existing_fingerprints: set[str] | None = None,
	offerings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
	"""Build a candidate or a review outcome without inventing missing values."""

	existing_fingerprints = existing_fingerprints or set()
	year = student.get("admission_year")
	if not year:
		return {"outcome": "review", "reason": "missing_admission_year", "student": student.get("name")}
	if offerings is not None:
		if not student.get("case_key"):
			return {"outcome": "review", "reason": "missing_case_key", "student": student.get("name")}
		if not student.get("admission_method"):
			return {"outcome": "review", "reason": "missing_admission_method", "student": student.get("name")}
		candidates = [
			offering
			for offering in offerings
			if offering.get("admission_year") == year
			and offering.get("campus") == student.get("branch")
			and offering.get("major") == student.get("major")
			and offering.get("admission_method") == student.get("admission_method")
			and offering.get("status") == "Active"
		]
		if len(candidates) != 1:
			return {
				"outcome": "review",
				"reason": "missing_offering" if not candidates else "ambiguous_offering",
				"student": student.get("name"),
			}
		offering = candidates[0]
		source_reference = f"CRM Lead:{student.get('name')}"
		attempt_key = canonical_attempt_key(student["case_key"], offering["name"], source_reference)
	else:
		offering = None
		source_reference = None
		attempt_key = None
	values = {
		"student": student.get("name"),
		**(
			{
				"case_key": student["case_key"],
				"offering": offering["name"],
				"application_attempt_key": attempt_key,
			}
			if offering
			else {}
		),
		"admission_year": year,
		"preference_order": 1,
		"preference": "Primary",
		"major": student.get("major"),
		"campus": student.get("branch"),
		"admission_method": student.get("admission_method"),
		"status": "Enrolled" if student.get("resolution") == "CREATED" else "Draft",
	}
	metadata = provenance(
		source_doctype="CRM Lead",
		source_name=str(student.get("name")),
		source_reference=source_reference,
		**values,
	)
	if metadata["idempotency_fingerprint"] in existing_fingerprints:
		return {
			"outcome": "existing",
			"student": student.get("name"),
			"fingerprint": metadata["idempotency_fingerprint"],
		}
	return {"outcome": "migrated", "values": values, **metadata}
