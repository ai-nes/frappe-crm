# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CRMMajor(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		import_source_id: DF.Int
		is_active: DF.Check
		major_code: DF.Data | None
		major_group: DF.Literal["Kỹ thuật - Công nghệ", "Kinh tế - Quản trị", "Truyền thông - Thiết kế", "Ngôn ngữ"]
		major_name: DF.Data
	# end: auto-generated types

	pass
