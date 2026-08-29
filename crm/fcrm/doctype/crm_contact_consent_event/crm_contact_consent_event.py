import frappe
from frappe.model.document import Document

EVENT_TYPE_TO_FLAG = {
	"Opted Out": "is_opted_out",
	"Marked Test": "is_test_record",
	"Bounced": "email_bounced",
}

_IMMUTABLE_FIELDS = (
	"naming_series",
	"student",
	"contact",
	"event_type",
	"occurred_at",
	"granted_at",
	"purpose",
	"scope",
	"source",
	"created_by",
	"command_receipt",
	"note",
)


class CRMContactConsentEvent(Document):
	def before_insert(self):
		if not self.occurred_at:
			self.occurred_at = self.granted_at or frappe.utils.now_datetime()
		if self.event_type == "Granted" and not self.granted_at:
			self.granted_at = self.occurred_at
		if not self.created_by:
			self.created_by = frappe.session.user

	def validate(self):
		if bool(self.student) == bool(self.contact):
			frappe.throw(
				"A consent event must target exactly one Student or Contact.", frappe.ValidationError
			)
		if self.event_type == "Granted":
			if not self.granted_at:
				frappe.throw("A granted consent event requires granted_at.", frappe.ValidationError)
			if not self.source:
				frappe.throw("A granted consent event requires a source.", frappe.ValidationError)
			if not self.purpose or not self.scope:
				frappe.throw("A granted consent event requires purpose and scope.", frappe.ValidationError)
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		for fieldname in _IMMUTABLE_FIELDS:
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw(
					f"{fieldname} is immutable on a CRM Contact Consent Event.",
					frappe.ValidationError,
				)

	def on_trash(self):
		frappe.throw("CRM Contact Consent Events are append-only.", frappe.PermissionError)


def sync_contact_consent_flag(doc: "CRMContactConsentEvent", method: str | None = None):
	"""after_insert hook: flips the matching snapshot flag on CRM Contact.

	Uses frappe.db.set_value (not doc.save()) to avoid re-triggering Contact's own
	validate/hook stack, and lets exceptions propagate so a failure rolls back the
	whole request transaction, including this just-inserted event.
	"""
	if not doc.contact:
		return
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
