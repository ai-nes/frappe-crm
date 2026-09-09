"""Derive Lead/Student source from the linked Campaign channel type."""

from __future__ import annotations

import frappe
from frappe import _


def campaign_source(campaign: str | None) -> str | None:
	"""Return the governed Lead Source mapped to a Campaign channel type."""
	if not campaign:
		return None

	channel_type = frappe.db.get_value("CRM Campaign", campaign, "channel_type")
	if not channel_type:
		frappe.throw(
			_("Campaign {0} must have a Channel Type before it can be linked to a Lead or Student.").format(
				campaign
			),
			frappe.ValidationError,
		)

	channel = frappe.db.get_value(
		"CRM Campaign Channel Type",
		channel_type,
		["code", "display_name"],
		as_dict=True,
	)
	if not channel:
		frappe.throw(
			_("Campaign {0} references an invalid Channel Type.").format(campaign),
			frappe.ValidationError,
		)

	channel_label = channel.get("display_name") or channel.get("code")
	if not channel_label:
		frappe.throw(
			_("Campaign Channel Type {0} has no display name or code.").format(channel_type),
			frappe.ValidationError,
		)
	source = frappe.db.get_value("CRM Lead Source", {"source_name": channel_label}, "name")
	if not source:
		frappe.throw(
			_("No Lead Source is mapped to Campaign Channel Type {0}.").format(channel_label),
			frappe.ValidationError,
		)
	if frappe.db.get_value("CRM Lead Source", source, "approval_state") == "Retired":
		frappe.throw(
			_("Lead Source {0} is retired and cannot be used for new attribution.").format(source),
			frappe.ValidationError,
		)
	return source


def resolve_campaign_reference(value: str | None) -> str | None:
	"""Resolve a Campaign name or stable code to its document name."""
	if not value:
		return None
	if frappe.db.exists("CRM Campaign", value):
		return value
	return frappe.db.get_value("CRM Campaign", {"stable_code": value}, "name")


def sync_campaign_source(doc, campaign: str | None = None) -> str | None:
	"""Set a document's source from its Campaign, when a Campaign is linked."""
	campaign = campaign or doc.get("campaign")
	if not campaign:
		return None
	source = campaign_source(campaign)
	doc.set("source", source)
	return source


def sync_student_campaign_source(doc) -> str | None:
	"""Inherit Campaign attribution from a Student's immutable source Lead."""
	campaign = doc.get("campaign")
	if doc.get("source_lead"):
		lead_campaign = frappe.db.get_value("CRM Lead", doc.get("source_lead"), "campaign")
		if lead_campaign:
			campaign = lead_campaign
			doc.set("campaign", campaign)
	return sync_campaign_source(doc, campaign)
