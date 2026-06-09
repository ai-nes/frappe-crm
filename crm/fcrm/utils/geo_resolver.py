import frappe


def resolve_province(value):
	"""Return CRM Province name (=province_name) given either province_name or province_code."""
	if not value:
		return value
	if frappe.db.exists("CRM Province", value):
		return value
	# Try by province_code field
	name = frappe.db.get_value("CRM Province", {"province_code": value}, "name")
	return name or value


def resolve_ward(ward_value, province_value=None):
	"""Return CRM Ward name (=ward_code) given either ward_code or ward_name.
	Province context narrows down when ward_name is not unique.
	"""
	if not ward_value:
		return ward_value
	if frappe.db.exists("CRM Ward", ward_value):
		return ward_value
	# Try by ward_name, scoped to province when available
	filters = {"ward_name": ward_value}
	if province_value:
		filters["province"] = province_value
	name = frappe.db.get_value("CRM Ward", filters, "name")
	if not name and province_value:
		# Retry without province in case province was already resolved differently
		name = frappe.db.get_value("CRM Ward", {"ward_name": ward_value}, "name")
	return name or ward_value
