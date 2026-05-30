# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CRMWard(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		import_source_id: DF.Int
		province: DF.Link | None
		ward_name: DF.Data
		ward_type: DF.Literal["Phường", "Xã", "Thị trấn"]
	# end: auto-generated types

	pass
