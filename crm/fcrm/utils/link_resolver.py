import frappe

from crm.fcrm.utils.geo_resolver import normalize_text


def resolve_link_strict(doctype, value, lookup_fields):
	"""Resolve an external Link value without silently choosing an ambiguous record."""
	if value is None or not str(value).strip():
		return None

	value = str(value).strip()
	if frappe.db.exists(doctype, value):
		return value

	for fieldname in lookup_fields:
		matches = frappe.get_all(doctype, filters={fieldname: value}, pluck="name", limit_page_length=2)
		if len(matches) == 1:
			return matches[0]
		if len(matches) > 1:
			_raise_ambiguous(doctype, value)

	candidates = frappe.get_all(doctype, fields=["name", *lookup_fields])
	matches = {
		candidate.name
		for candidate in candidates
		if any(normalize_text(candidate.get(fieldname)) == normalize_text(value) for fieldname in lookup_fields)
	}
	if len(matches) == 1:
		return matches.pop()
	if len(matches) > 1:
		_raise_ambiguous(doctype, value)

	frappe.throw(
		f"Không tìm thấy {doctype} phù hợp với <b>{value}</b>.",
		title="Dữ liệu liên kết không hợp lệ",
	)


def _raise_ambiguous(doctype, value):
	frappe.throw(
		f"Giá trị <b>{value}</b> khớp với nhiều bản ghi {doctype}. Vui lòng gửi mã hoặc docname chính xác.",
		title="Dữ liệu liên kết không rõ ràng",
	)
