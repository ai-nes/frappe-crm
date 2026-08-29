"""Phase 6: seed the "Campaign Touched" CRM Interaction Type.

A CRM Campaign Touchpoint insert is customer activity and the operating
model's condition #1 ("no customer activity outside Interaction") requires
it to be captured -- previously only CRM Event Participation emitted an
Interaction, leaving campaign touchpoints invisible to interaction history
and therefore to attribution logic. See
crm.fcrm.interaction_log.create_interaction_from_campaign_touchpoint_insert.
"""

import frappe


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_interaction", force=True)

	if not frappe.db.exists("CRM Term", {"term_name": "Campaign Touched", "category": "interaction_type"}):
		frappe.get_doc(
			{
				"doctype": "CRM Term", "term_name": "Campaign Touched", "category": "interaction_type",
			}
		).insert(ignore_permissions=True)
