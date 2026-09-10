import re
import unicodedata

import frappe


def normalize_text(value):
	"""Lowercase, strip Vietnamese diacritics, collapse whitespace to underscores."""
	if not value:
		return value
	text = str(value).strip()
	text = text.replace("Đ", "D").replace("đ", "d")
	text = unicodedata.normalize("NFKD", text)
	text = "".join(ch for ch in text if not unicodedata.combining(ch))
	text = text.lower()
	text = re.sub(r"\s+", " ", text).strip()
	text = text.replace(" ", "_")
	return text


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
		scoped_filters.extend(
			[
				{"ward_code": ward_value, "province": province},
				{"ward_name": ward_value, "province": province},
			]
		)

	name = _first_matching_docname(
		"CRM Ward",
		[
			*scoped_filters,
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
	if province.get("name"):
		scoped_filters.extend(
			[
				{"school_code": school_value, "province": province.name},
				{"school_name": school_value, "province": province.name},
			]
		)

	name = _first_matching_docname(
		"CRM High School",
		[
			*scoped_filters,
			{"school_code": school_value},
			{"school_name": school_value},
		],
	)
	return name or school_value


def resolve_high_school_strict(school_value, province_value=None):
	"""Return CRM High School docname, raising a clear error instead of falling back
	to the raw input when no confident match exists (used for import-time validation)."""
	if not school_value:
		return school_value
	if frappe.db.exists("CRM High School", school_value):
		return school_value

	province = _get_province_context(province_value)
	code_matches = frappe.get_all(
		"CRM High School",
		filters={"school_code": school_value},
		fields=["name", "province"],
	)
	if len(code_matches) == 1:
		return code_matches[0].name
	if len(code_matches) > 1:
		scoped_matches = [
			match for match in code_matches if province.get("name") and match.province == province.name
		]
		if len(scoped_matches) == 1:
			return scoped_matches[0].name
		frappe.throw(
			f"Mã trường <b>{school_value}</b> khớp với nhiều trường học. "
			"Vui lòng bổ sung tỉnh/thành để xác định trường chính xác.",
			title="Trường học không rõ ràng",
		)

	target = normalize_text(school_value)

	candidates = frappe.get_all(
		"CRM High School",
		fields=["name", "school_name", "province"],
		order_by="name",
	)
	matches = [c for c in candidates if normalize_text(c.school_name) == target]

	if not matches:
		frappe.throw(
			f"Không tìm thấy trường <b>{school_value}</b> trong hệ thống. Vui lòng kiểm tra lại tên trường.",
			title="Trường học không hợp lệ",
		)

	distinct_provinces = {m.province for m in matches}
	if len(distinct_provinces) <= 1:
		# Duplicate rows within the same province are a data-quality issue, not
		# the multi-province ambiguity FR-04 cares about — pick the first match.
		return matches[0].name

	if province.get("name"):
		scoped = [m for m in matches if m.province == province.name]
		if len(scoped) == 1:
			return scoped[0].name

	province_names = sorted(
		{
			frappe.db.get_value("CRM Province", m.province, "province_name") or m.province or "?"
			for m in matches
		}
	)
	frappe.throw(
		f"Trường <b>{school_value}</b> tồn tại ở nhiều tỉnh ({', '.join(province_names)}). "
		"Vui lòng bổ sung đúng tỉnh/thành để xác định trường chính xác.",
		title="Cần bổ sung tỉnh/thành",
	)


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
