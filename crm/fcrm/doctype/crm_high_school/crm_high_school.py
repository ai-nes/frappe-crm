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
				"width": "16rem",
			},
			{
				"label": "School Code",
				"type": "Data",
				"key": "school_code",
				"width": "10rem",
			},
			{
				"label": "School Type",
				"type": "Link",
				"key": "school_type",
				"options": "CRM School Type",
				"width": "10rem",
			},
			{
				"label": "Ward",
				"type": "Link",
				"key": "ward",
				"options": "CRM Ward",
				"width": "12rem",
			},
			{
				"label": "Province",
				"type": "Link",
				"key": "province",
				"options": "CRM Province",
				"width": "12rem",
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
			"school_name",
			"school_code",
			"school_type",
			"ward",
			"province",
			"region",
			"modified",
		]
		return {"columns": columns, "rows": rows}
