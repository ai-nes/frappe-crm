# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from crm.fcrm.utils.geo_resolver import resolve_province, resolve_ward


class CRMHighSchool(Document):
	def before_insert(self):
		self._resolve_geo()

	def before_save(self):
		self._resolve_geo()

	def _resolve_geo(self):
		if self.province:
			self.province = resolve_province(self.province)
		if self.ward:
			self.ward = resolve_ward(self.ward, self.province)

	@staticmethod
	def default_list_data():
		columns = [
			{
				"label": "School Name",
				"type": "Data",
				"key": "school_name",
				"width": "20rem",
			},
			{
				"label": "School Type",
				"type": "Link",
				"key": "school_type",
				"options": "CRM School Type",
				"width": "10rem",
			},
			{
				"label": "Province",
				"type": "Data",
				"key": "province_name",
				"width": "12rem",
			},
			{
				"label": "Ward",
				"type": "Data",
				"key": "ward_name",
				"width": "14rem",
			},
			{
				"label": "Region",
				"type": "Link",
				"key": "region",
				"options": "CRM Region",
				"width": "10rem",
			},
			{
				"label": "Address",
				"type": "Small Text",
				"key": "address",
				"width": "20rem",
			},
		]
		rows = [
			"name",
			"school_name",
			"school_type",
			"province_name",
			"ward_name",
			"region",
			"address",
			"modified",
		]
		return {"columns": columns, "rows": rows}
