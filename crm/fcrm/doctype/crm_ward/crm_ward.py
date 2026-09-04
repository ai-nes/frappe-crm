# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from crm.fcrm.utils.geo_hierarchy import block_delete_if_has_children, block_parent_change_if_has_children


class CRMWard(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		import_source_id: DF.Int
		province: DF.Link | None
		ward_code: DF.Data | None
		ward_name: DF.Data
		ward_type: DF.Literal["Ward", "Commune", "Township"]
		zone: DF.Link | None
	# end: auto-generated types

	def before_validate(self):
		self._sync_canonical_province()

	def validate(self):
		block_parent_change_if_has_children(self, "CRM High School", "ward", "zone")

	def _sync_canonical_province(self):
		if not self.zone:
			return
		province = frappe.db.sql(
			"""
			SELECT c.province
			FROM `tabCRM Zone` z
			JOIN `tabCRM Cluster` c ON c.name = z.cluster
			WHERE z.name = %s
			""",
			(self.zone,),
		)
		if province:
			self.province = province[0][0]

	def on_trash(self):
		block_delete_if_has_children(self, "CRM High School", "ward")
