# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CRMPlatform(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		lead_source: DF.Link
		platform_name: DF.Data
		sub_channel: DF.Literal["", "Form", "Landing Page"]
	# end: auto-generated types

	pass
