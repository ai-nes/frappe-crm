"""Phase 6: first-touch / last-touch / multi-touch attribution, computed from
the CRM Campaign Touchpoint and CRM Event Participation junction tables (the
Phase 5 many-to-many sources), not from the deprecated singular CRM Contact
crm_campaign/crm_event fields -- attribution is meant to reward every touch a
lead actually had, which the old single-value fields cannot represent.

A CRM Event Participation touchpoint's campaign is resolved via its Event's
crm_campaign link, so an event-driven touch still attributes to a campaign.
"""

import frappe


def _campaign_touchpoints(crm_contact):
	rows = frappe.db.get_all(
		"CRM Campaign Touchpoint",
		filters={"crm_contact": crm_contact},
		fields=["name", "crm_campaign", "touched_at", "source"],
	)
	return [
		{
			"touched_at": row.touched_at,
			"campaign": row.crm_campaign,
			"source": "Campaign Touchpoint",
			"reference_doctype": "CRM Campaign Touchpoint",
			"reference_docname": row.name,
		}
		for row in rows
		if row.touched_at
	]


def _event_touchpoints(crm_contact):
	rows = frappe.db.get_all(
		"CRM Event Participation",
		filters={"crm_contact": crm_contact},
		fields=["name", "crm_event", "registered_at"],
	)
	touchpoints = []
	for row in rows:
		if not row.registered_at:
			continue
		campaign = frappe.db.get_value("CRM Event", row.crm_event, "crm_campaign")
		touchpoints.append(
			{
				"touched_at": row.registered_at,
				"campaign": campaign,
				"event": row.crm_event,
				"source": "Event Participation",
				"reference_doctype": "CRM Event Participation",
				"reference_docname": row.name,
			}
		)
	return touchpoints


def get_contact_touchpoints(crm_contact):
	"""All campaign/event touchpoints for a contact, oldest first. Touchpoints
	whose campaign could not be resolved (e.g. an orphaned Event with no
	crm_campaign) are kept but with campaign=None, since callers may still
	want the raw touch timeline."""
	touchpoints = _campaign_touchpoints(crm_contact) + _event_touchpoints(crm_contact)
	touchpoints.sort(key=lambda t: t["touched_at"])
	return touchpoints


def get_first_touch(crm_contact):
	touchpoints = get_contact_touchpoints(crm_contact)
	return touchpoints[0] if touchpoints else None


def get_last_touch(crm_contact):
	touchpoints = get_contact_touchpoints(crm_contact)
	return touchpoints[-1] if touchpoints else None


def get_multi_touch_attribution(crm_contact):
	"""Linear (equal-credit) multi-touch model: every touchpoint with a
	resolvable campaign gets an equal fraction of the credit, grouped by
	campaign. Touchpoints with no resolvable campaign are excluded from
	credit but don't shrink other campaigns' shares."""
	touchpoints = [t for t in get_contact_touchpoints(crm_contact) if t.get("campaign")]
	if not touchpoints:
		return {}

	credit_per_touch = 1.0 / len(touchpoints)
	credit_by_campaign = {}
	for touchpoint in touchpoints:
		campaign = touchpoint["campaign"]
		credit_by_campaign[campaign] = credit_by_campaign.get(campaign, 0.0) + credit_per_touch
	return credit_by_campaign


def get_last_touch_campaign_by_contact():
	"""Site-wide map of {crm_contact: campaign} for each contact's LAST
	touchpoint (by touched_at, across both junction tables) that resolved to a
	campaign. One pass over both junction tables -- callers that need this
	broken down per-campaign (e.g. a per-campaign cost/conversion loop) should
	call this ONCE and bucket the result themselves, rather than calling
	get_campaign_names_by_last_touch in a per-campaign loop, which would
	re-scan both tables on every iteration."""
	touchpoint_rows = frappe.db.get_all(
		"CRM Campaign Touchpoint",
		fields=["crm_contact", "crm_campaign as campaign", "touched_at"],
	)
	event_rows = frappe.db.get_all(
		"CRM Event Participation",
		fields=["crm_contact", "crm_event", "registered_at as touched_at"],
	)
	event_campaign_by_event = {}
	for row in event_rows:
		if row.crm_event not in event_campaign_by_event:
			event_campaign_by_event[row.crm_event] = frappe.db.get_value(
				"CRM Event", row.crm_event, "crm_campaign"
			)
		row["campaign"] = event_campaign_by_event[row.crm_event]

	last_touch_by_contact = {}
	for row in touchpoint_rows + event_rows:
		if not row.touched_at or not row.get("campaign"):
			continue
		existing = last_touch_by_contact.get(row.crm_contact)
		if not existing or row.touched_at > existing["touched_at"]:
			last_touch_by_contact[row.crm_contact] = {"touched_at": row.touched_at, "campaign": row["campaign"]}

	return {contact: last_touch["campaign"] for contact, last_touch in last_touch_by_contact.items()}


def get_campaign_names_by_last_touch(campaign):
	"""Contact names whose LAST touchpoint belongs to the given campaign --
	used by dashboards that want last-touch-attributed conversion counts
	instead of "touched at any point" counts.

	Callers looping over multiple campaigns should use
	get_last_touch_campaign_by_contact() directly instead of calling this
	function per campaign, to avoid re-scanning both junction tables once per
	campaign."""
	last_touch_by_contact = get_last_touch_campaign_by_contact()
	return {contact for contact, camp in last_touch_by_contact.items() if camp == campaign}


@frappe.whitelist()
def get_contact_attribution(contact):
	"""API entry point: first-touch, last-touch, and multi-touch credit
	breakdown for one CRM Contact. Used by the student/contact drill-down and
	by manual spot-checks against a seeded dataset."""
	if not frappe.db.exists("CRM Contact", contact):
		frappe.throw(f"CRM Contact {contact} does not exist")

	touchpoints = get_contact_touchpoints(contact)
	return {
		"firstTouch": touchpoints[0] if touchpoints else None,
		"lastTouch": touchpoints[-1] if touchpoints else None,
		"multiTouch": get_multi_touch_attribution(contact),
		"touchpoints": touchpoints,
	}
