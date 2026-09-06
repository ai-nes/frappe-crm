"""Shared, send-time consent guard for all outbound action paths."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def contactability_allows(
	contactability: Mapping | None,
	*,
	linked_contacts: Sequence[str],
	action_contact: str | None,
	channel: str | None,
) -> bool:
	"""Return true only for one explicitly consented, bound recipient."""
	if not isinstance(contactability, Mapping) or contactability.get("consent") is not True:
		return False
	if not channel or str(channel).upper() not in {
		str(value).upper() for value in (contactability.get("channels") or [])
	}:
		return False
	contacts = [str(contact) for contact in linked_contacts if contact]
	return len(contacts) == 1 and action_contact == contacts[0]


def current_outreach_consent_allows(
	*, student: str | None, action_contact: str | None, channel: str | None
) -> bool:
	"""Resolve authoritative consent and recipient binding immediately before send."""
	if not student:
		return False
	from crm.api.student_decision_context import _contactability_projection
	from crm.fcrm.student_contact_conversion import contacts_for_student

	return contactability_allows(
		_contactability_projection(student),
		linked_contacts=contacts_for_student(student),
		action_contact=action_contact,
		channel=channel,
	)
