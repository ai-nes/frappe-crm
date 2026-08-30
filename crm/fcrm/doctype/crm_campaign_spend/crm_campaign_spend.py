# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from crm.fcrm.legacy_fact_guard import reject_legacy_fact_write


class CRMCampaignSpend(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amount: DF.Currency
		campus: DF.Link | None
		clicks: DF.Int
		crm_campaign: DF.Link | None
		impressions: DF.Int
		lead_source: DF.Link
		naming_series: DF.Literal["SPEND-.YYYY.-"]
		notes: DF.SmallText | None
		platform: DF.Link | None
		spend_date: DF.Date
	# end: auto-generated types

	def before_validate(self):
		reject_legacy_fact_write("CRM Campaign Spend")
