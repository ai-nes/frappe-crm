import frappe

from crm.install import add_default_quick_filters


def execute():
	for doctype in ("CRM Student", "CRM Contact"):
		for name in frappe.get_all("CRM View Settings", filters={"dt": doctype}, pluck="name"):
			frappe.delete_doc("CRM View Settings", name, force=True)

	add_default_quick_filters()
