import frappe


def get_site_info(site_info):
	# called via hook
	return {"activation": get_sales_data(site_info)}


def get_sales_data(site_info):
	activation_level = site_info.get("activation", {}).get("activation_level", 0)
	sales_data = site_info.get("activation", {}).get("sales_data", [])
	doctypes = [
		"CRM Student",
		"CRM Contact",
		"CRM High School",
		"CRM Person",
		"CRM Campaign",
		"CRM Event",
		"CRM Interaction",
		"CRM Intent",
		"CRM Staff",
		"Contact",
		"CRM Task",
		"FCRM Note",
		"CRM Call Log",
		"CRM Lead Source",
		"CRM Lost Reason",
		"CRM Form Script",
		"CRM Fields Layout",
		"CRM View Settings",
	]

	for doctype in doctypes:
		count = frappe.db.count(doctype)
		sales_data.append({doctype: count})

	return {"activation_level": activation_level, "sales_data": sales_data}
