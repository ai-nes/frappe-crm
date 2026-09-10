from crm.services.outreach_consent import contactability_allows


def test_contactability_allows_only_the_unique_explicitly_consented_recipient():
	context = {"consent": True, "channels": ["CALL", "EMAIL"]}
	assert contactability_allows(
		context, linked_contacts=["CON-1"], action_contact="CON-1", channel="CALL"
	)
	assert not contactability_allows(
		context, linked_contacts=["CON-1"], action_contact="CON-2", channel="CALL"
	)
	assert not contactability_allows(
		context, linked_contacts=["CON-1", "CON-2"], action_contact="CON-1", channel="CALL"
	)
	assert not contactability_allows(
		context, linked_contacts=["CON-1"], action_contact="CON-1", channel="MESSAGE"
	)
