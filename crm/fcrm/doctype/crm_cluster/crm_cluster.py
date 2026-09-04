# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe import _
from frappe.model.document import Document

from crm.fcrm.utils.geo_hierarchy import block_delete_if_has_children, block_parent_change_if_has_children


class CRMCluster(Document):
	def validate(self):
		block_parent_change_if_has_children(self, "CRM Zone", "cluster", "province")

	def on_trash(self):
		block_delete_if_has_children(
			self,
			"CRM Zone",
			"cluster",
			_("Cannot delete Cluster {0}: it still has Zones under it. Deactivate it instead.").format(
				self.cluster_name
			),
		)
