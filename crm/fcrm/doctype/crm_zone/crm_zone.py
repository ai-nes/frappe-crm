# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe import _
from frappe.model.document import Document

from crm.fcrm.utils.geo_hierarchy import block_delete_if_has_children, block_parent_change_if_has_children


class CRMZone(Document):
	def validate(self):
		block_parent_change_if_has_children(self, "CRM Ward", "zone", "cluster")

	def on_trash(self):
		block_delete_if_has_children(
			self,
			"CRM Ward",
			"zone",
			_("Cannot delete Zone {0}: it still has Wards under it. Deactivate it instead.").format(
				self.zone_name
			),
		)
		block_delete_if_has_children(
			self,
			"CRM Team Zone Assignment",
			"zone",
			_("Cannot delete Zone {0}: it still has Team assignments. Retire them first.").format(
				self.zone_name
			),
		)
		block_delete_if_has_children(
			self,
			"CRM High School Assignment",
			"zone",
			_("Cannot delete Zone {0}: it still has High School assignments. Re-point them first.").format(
				self.zone_name
			),
		)
