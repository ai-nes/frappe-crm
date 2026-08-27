"""Move DocTypes into bounded-context modules without changing their tables."""

from __future__ import annotations

import frappe

MODULES = {
	"CRM Identity": (
		"CRM Person", "CRM Student Identity", "CRM Student Identity Identifier", "CRM Student Case Key",
		"CRM Parent Contact Authority", "CRM Influence", "CRM Contact Consent Event", "CRM Student Contact Conversion",
	),
	"CRM Student Lifecycle": (
		"CRM Student", "CRM Student Lifecycle Event", "CRM Student Decision Event", "CRM Student Ownership Event",
		"CRM Student Outcome", "CRM Student Command Receipt", "CRM Student Intake Review",
		"CRM Student Dispatch Receipt", "CRM Student Revision Journal", "CRM Event Stream Cursor", "CRM Assignment Log",
	),
	"CRM Routing & SLA": (
		"CRM Student Pool", "CRM Student Routing Policy", "CRM Student Routing Request", "CRM Student SLA Policy",
		"CRM Student SLA Attempt", "CRM Student SLA Event", "CRM Student SLA Delivery", "CRM Student SLA Delivery Attempt",
	),
	"CRM Scoring": (
		"CRM Score Template", "CRM Score Rule", "CRM Score Signal", "CRM Score History", "CRM Score History Detail",
	),
	"CRM Engagement": (
		"CRM Interaction", "CRM Recommendation",
		"CRM Action", "CRM Action Revision", "CRM Agent Event", "Call Log", "FCRM Note", "Task",
	),
	"CRM Marketing": (
		"CRM Lead Source", "CRM Platform", "CRM Campaign", "CRM Campaign Spend",
		"CRM Event", "CRM Marketing Engagement", "CRM Segment",
	),
	"CRM Master Data": (
		"CRM Academic Year Config", "CRM Academic Year Line", "CRM Admission Year", "CRM Education Program",
		"CRM High School", "CRM Major", "CRM Province", "CRM Province Former Name", "CRM Ward", "CRM Master Data Change",
		"CRM Master Data Change Approval",
	),
	"CRM AI": ("CRM AI Lead Insight", "CRM AI Lead Insight Item", "CRM AI Personal Email Draft", "CRM AI Capability Grant"),
	"CRM Org": ("CRM Campus", "CRM Department", "CRM Staff", "CRM Team", "CRM Team Membership"),
	"CRM Config": (
		"FCRM Settings", "Global Settings", "Dropdown Item", "Fields Layout", "Form Script", "View Settings",
		"Telephony Agent", "Telephony Phone", "Exotel Settings", "Twilio Settings", "Notification", "Invitation",
		"Dashboard", "Holiday", "Holiday List", "Service Day", "Service Level Agreement", "Service Level Priority",
	),
}


def execute():
	updated = []
	for module, doctypes in MODULES.items():
		for doctype in doctypes:
			if not frappe.db.exists("DocType", doctype):
				continue
			if frappe.db.get_value("DocType", doctype, "module") != module:
				frappe.db.set_value("DocType", doctype, "module", module, update_modified=False)
				updated.append(doctype)
	return {"updated": updated, "module_count": len(MODULES)}
