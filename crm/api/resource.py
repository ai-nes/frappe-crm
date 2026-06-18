import json

import frappe

from crm.utils import get_phone_lookup_terms


PHONE_LOOKUP_DOCTYPES = {"CRM Student", "CRM Contact"}


def normalize_resource_phone_filters():
	if frappe.request.method != "GET":
		return

	path = (frappe.request.path or "").strip("/")
	parts = path.split("/")
	if len(parts) < 3 or parts[0] != "api" or parts[1] != "resource":
		return

	doctype = parts[2]
	if doctype not in PHONE_LOOKUP_DOCTYPES:
		return

	filters = frappe.form_dict.get("filters")
	if not filters:
		return

	normalized_filters = normalize_phone_filters(filters)
	if normalized_filters is None:
		return

	frappe.form_dict["filters"] = json.dumps(normalized_filters)


def normalize_phone_filters(filters):
	if isinstance(filters, str):
		try:
			filters = json.loads(filters)
		except ValueError:
			return None

	if isinstance(filters, dict):
		return normalize_phone_filter_dict(filters)

	if isinstance(filters, list):
		return normalize_phone_filter_list(filters)

	return None


def normalize_phone_filter_dict(filters):
	value = filters.get("phone")
	terms = get_phone_lookup_terms(value) if isinstance(value, str) else []
	if not terms:
		return filters

	return {
		**filters,
		"phone": ["in", terms],
	}


def normalize_phone_filter_list(filters):
	normalized = []
	for condition in filters:
		normalized.append(normalize_phone_filter_condition(condition))
	return normalized


def normalize_phone_filter_condition(condition):
	if not isinstance(condition, list):
		return condition

	field_index = None
	operator_index = None
	value_index = None

	if len(condition) >= 3 and condition[0] == "phone":
		field_index, operator_index, value_index = 0, 1, 2
	elif len(condition) >= 4 and condition[1] == "phone":
		field_index, operator_index, value_index = 1, 2, 3

	if field_index is None:
		return condition

	operator = str(condition[operator_index]).lower()
	value = condition[value_index]
	if operator not in ("=", "==") or not isinstance(value, str):
		return condition

	terms = get_phone_lookup_terms(value)
	if not terms:
		return condition

	rewritten = [*condition]
	rewritten[operator_index] = "in"
	rewritten[value_index] = terms
	return rewritten
