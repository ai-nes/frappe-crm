import frappe
from frappe import _

from crm.integrations.ai_email import generate_mock_draft, get_provider


@frappe.whitelist()
def generate_email_draft(
	contact: str, purpose: str, instruction: str | None = None, ai_insight: str | None = None
):
	"""Generate a mock AI email draft for a contact and persist it as a
	CRM AI Personal Email Draft record. Enforces contact read permission
	and the contact's opt-out consent flag before creating anything.
	"""
	if not frappe.has_permission("CRM Contact", "read", contact):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if frappe.db.get_value("CRM Contact", contact, "is_opted_out"):
		frappe.throw(_("This contact has opted out of communications — an AI draft cannot be generated."))

	draft = frappe.get_doc(
		{
			"doctype": "CRM AI Personal Email Draft",
			"contact": contact,
			"purpose": purpose,
			"instruction": instruction,
			"ai_insight": ai_insight,
			"status": "Generating",
		}
	)
	draft.insert()

	provider = get_provider()
	try:
		if provider != "mock":
			frappe.throw(_("Unsupported AI email draft provider: {0}").format(provider))
		subject, body = generate_mock_draft(contact, purpose, instruction, ai_insight)
	except Exception:
		frappe.db.set_value("CRM AI Personal Email Draft", draft.name, "status", "Failed")
		raise

	frappe.db.set_value(
		"CRM AI Personal Email Draft",
		draft.name,
		{"generated_subject": subject, "generated_body": body, "status": "Draft"},
	)

	return {"name": draft.name, "subject": subject, "body": body, "status": "Draft"}


@frappe.whitelist()
def cancel_draft(draft: str):
	"""Mark an abandoned draft as Cancelled (used by Discard and Regenerate)."""
	doc = frappe.get_doc("CRM AI Personal Email Draft", draft)
	doc.status = "Cancelled"
	doc.save()
	return {"name": doc.name, "status": doc.status}
