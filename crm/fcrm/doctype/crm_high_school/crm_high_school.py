# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CRMHighSchool(Document):
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
