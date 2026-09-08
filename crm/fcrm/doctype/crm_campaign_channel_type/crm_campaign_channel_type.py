import frappe
from frappe import _

from crm.fcrm.lookup_doctype import LookupDocument


class CRMCampaignChannelType(LookupDocument):
	"""Controlled vocabulary for campaign channel types and their modes."""

	def validate(self):
		super().validate()
		if not self.is_online and not self.is_offline:
			frappe.throw(
				_("A campaign channel type must support Online, Offline, or both modes."),
				frappe.ValidationError,
			)
