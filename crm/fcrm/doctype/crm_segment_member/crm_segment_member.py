import frappe
from frappe.model.document import Document

from crm.fcrm.segment_lifecycle import COMMAND_FLAG
from crm.fcrm.segment_rules import fail


class CRMSegmentMember(Document):
	def validate(self):
		if not frappe.flags.get(COMMAND_FLAG):
			fail("Snapshot members are command-only.", "FORBIDDEN", permission=True)

	def on_trash(self):
		fail("Snapshot membership is immutable.", "FORBIDDEN", permission=True)
