# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CRMHighSchool(Document):
	@staticmethod
	def default_list_data():
		columns = [
			{
				"label": "Province Code",
				"type": "Data",
				"key": "province_code",
				"width": "8rem",
			},
			{
				"label": "Province",
				"type": "Link",
				"key": "province",
				"options": "CRM Province",
				"width": "12rem",
			},
			{
				"label": "Ward Code",
				"type": "Data",
				"key": "ward_code",
				"width": "8rem",
			},
			{
				"label": "Ward",
				"type": "Link",
				"key": "ward",
				"options": "CRM Ward",
				"width": "12rem",
			},
			{
				"label": "School Name",
				"type": "Data",
				"key": "school_name",
				"width": "16rem",
			},
			{
				"label": "School Code",
				"type": "Data",
				"key": "school_code",
				"width": "10rem",
			},
			{
				"label": "Address",
				"type": "Small Text",
				"key": "address",
				"width": "18rem",
			},
			{
				"label": "Region",
				"type": "Link",
				"key": "region",
				"options": "CRM Region",
				"width": "8rem",
			},
			{
				"label": "Last Modified",
				"type": "Datetime",
				"key": "modified",
				"width": "8rem",
			},
		]
		rows = [
			"name",
			"province_code",
			"province",
			"ward_code",
			"ward",
			"school_code",
			"school_name",
			"address",
			"region",
			"modified",
		]
		return {"columns": columns, "rows": rows}
