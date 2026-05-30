# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CRMProvince(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		city_number: DF.Data | None
		city_type: DF.Literal["Thành phố trực thuộc TW", "Tỉnh"]
		import_source_id: DF.Int
		province_name: DF.Data
	# end: auto-generated types

	pass
