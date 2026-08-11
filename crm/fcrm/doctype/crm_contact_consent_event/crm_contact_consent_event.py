import frappe
from frappe.model.document import Document

EVENT_TYPE_TO_FLAG = {
	"Opted Out": "is_opted_out",
	"Marked Test": "is_test_record",
	"Bounced": "email_bounced",
}


class CRMContactConsentEvent(Document):
	def before_insert(self):
		if not self.occurred_at:
			self.occurred_at = frappe.utils.now_datetime()
		if not self.created_by:
			self.created_by = frappe.session.user


def sync_contact_consent_flag(doc: "CRMContactConsentEvent", method: str | None = None):
	"""after_insert hook: flips the matching snapshot flag on CRM Contact.

	Uses frappe.db.set_value (not doc.save()) to avoid re-triggering Contact's own
	validate/hook stack, and lets exceptions propagate so a failure rolls back the
	whole request transaction, including this just-inserted event.
	"""
	flag_field = EVENT_TYPE_TO_FLAG.get(doc.event_type)
	if not flag_field:
		# "Re-subscribed" and "Suppressed" don't map to a single boolean flag flip
		if doc.event_type == "Re-subscribed":
			flag_field = "is_opted_out"
			target_value = 0
		else:
			return
	else:
		target_value = 1

	current_value = frappe.db.get_value("CRM Contact", doc.contact, flag_field)
	if current_value == target_value:
		return

	frappe.db.set_value("CRM Contact", doc.contact, flag_field, target_value, update_modified=False)
