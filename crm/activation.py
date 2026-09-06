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
		"CRM High School Annual Snapshot",
		"CRM School Activity",
		"CRM School Stakeholder",
		"CRM Person",
		"CRM Campaign",
		"CRM Event",
		"CRM Interaction",
		"CRM Intent",
		"CRM Staff",
		"Contact",
		"Task",
		"FCRM Note",
		"Call Log",
		"CRM Lead Source",
		"Form Script",
		"Fields Layout",
		"View Settings",
	]

	for doctype in doctypes:
		count = frappe.db.count(doctype)
		sales_data.append({doctype: count})

	return {"activation_level": activation_level, "sales_data": sales_data}
