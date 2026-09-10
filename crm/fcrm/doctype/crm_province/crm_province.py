# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from crm.fcrm.utils.geo_hierarchy import block_delete_if_has_children


class CRMProvince(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		city_type: DF.Literal["Centrally Controlled City", "Province"]
		import_source_id: DF.Int
		province_code: DF.Data
		province_name: DF.Data
		region: DF.Link | None
	# end: auto-generated types

	def on_trash(self):
		block_delete_if_has_children(
			self,
			"CRM Cluster",
			"province",
			"Cannot delete Province {0}: it still has Clusters under it. Deactivate it instead.".format(
				self.province_name
			),
		)
		block_delete_if_has_children(
			self,
			"CRM Campus",
			"province",
			"Cannot delete Province {0}: it is still linked to a Campus. Re-point the Campus first.".format(
				self.province_name
			),
		)
		for doctype in ("CRM Student", "CRM High School", "CRM Lead"):
			block_delete_if_has_children(
				self,
				doctype,
				"province",
				"Cannot delete Province {0}: it is still referenced by {1}.".format(
					self.province_name, doctype
				),
			)
