import frappe


def resolve_province(value):
	"""Return CRM Province docname given either province docname, name, or code."""
	if not value:
		return value
	if frappe.db.exists("CRM Province", value):
		return value
	name = frappe.db.get_value("CRM Province", {"province_code": value}, "name")
	if not name:
		name = _get_unique_docname("CRM Province", {"province_name": value})
	return name or value


def resolve_ward(ward_value, province_value=None):
	"""Return CRM Ward docname given ward docname, code, or name."""
	if not ward_value:
		return ward_value
	if frappe.db.exists("CRM Ward", ward_value):
		return ward_value

	province = resolve_province(province_value) if province_value else None
	scoped_filters = []
	if province:
		scoped_filters.extend([
			{"ward_code": ward_value, "province": province},
			{"ward_name": ward_value, "province": province},
		])

	name = _first_matching_docname(
		"CRM Ward",
		scoped_filters
		+ [
			{"ward_code": ward_value},
			{"ward_name": ward_value},
		],
	)
	return name or ward_value


def resolve_high_school(school_value, province_value=None):
	"""Return CRM High School docname given school docname, code, or name."""
	if not school_value:
		return school_value
	if frappe.db.exists("CRM High School", school_value):
		return school_value

	province = _get_province_context(province_value)
	scoped_filters = []
	if province.get("province_code"):
		scoped_filters.extend([
			{"school_code": school_value, "province_code": province.province_code},
			{"school_name": school_value, "province_code": province.province_code},
		])
	if province.get("province_name"):
		scoped_filters.append({"school_name": school_value, "province_name": province.province_name})

	name = _first_matching_docname(
		"CRM High School",
		scoped_filters
		+ [
			{"school_code": school_value},
			{"school_name": school_value},
		],
	)
	return name or school_value


def _get_province_context(value):
	if not value:
		return frappe._dict()

	name = resolve_province(value)
	if not frappe.db.exists("CRM Province", name):
		return frappe._dict()

	return frappe._dict(
		frappe.db.get_value(
			"CRM Province",
			name,
			["name", "province_code", "province_name"],
			as_dict=True,
		)
		or {}
	)


def _first_matching_docname(doctype, filters_list):
	for filters in filters_list:
		name = _get_unique_docname(doctype, filters)
		if name:
			return name


def _get_unique_docname(doctype, filters):
	names = frappe.get_all(doctype, filters=filters, pluck="name", limit_page_length=2)
	return names[0] if len(names) == 1 else None
