"""Evidence-only decisions for Contact → Person stakeholder migration."""

from __future__ import annotations

from typing import Any

from crm.fcrm.admissions_migration import stable_fingerprint


def stakeholder_crosswalk_decision(
	legacy_row: dict[str, Any],
	contact_to_people: dict[str, list[str] | tuple[str, ...] | str],
) -> dict[str, Any]:
	"""Return a mapped row only when the Contact has exactly one Person match."""

	source_doctype = str(legacy_row.get("doctype") or "").strip()
	source_name = str(legacy_row.get("name") or "").strip()
	contact = str(legacy_row.get("contact") or "").strip()
	if (
		source_doctype not in {"CRM School Contact", "CRM School Relationship"}
		or not source_name
		or not contact
	):
		return {"outcome": "quarantined", "reason": "invalid_source", "source_name": source_name}
	people = contact_to_people.get(contact, [])
	if isinstance(people, str):
		people = [people]
	people = sorted({str(person).strip() for person in people if str(person).strip()})
	if not people:
		return {"outcome": "quarantined", "reason": "no_person_evidence", "source_name": source_name}
	if len(people) != 1:
		return {"outcome": "quarantined", "reason": "collision", "source_name": source_name}
	person = people[0]
	return {
		"outcome": "migrated",
		"values": {
			"legacy_doctype": source_doctype,
			"legacy_name": source_name,
			"contact": contact,
			"person": person,
			"match_method": "Exact Contact Person",
			"evidence_reference": f"{source_doctype}:{source_name}->{contact}:{person}",
			"confidence": 100,
			"reviewer_outcome": "Pending",
			"status": "Pending",
		},
		"idempotency_fingerprint": stable_fingerprint(source_doctype, source_name, contact, person),
	}
