import frappe

from crm.fcrm import student_segments as service
from crm.fcrm.segment_rules import FIELDS, OPERATORS, integer


@frappe.whitelist()
def get_fields():
	frappe.has_permission("CRM Student", "read", throw=True)
	return [
		{"fieldname": name, **meta, "operators": OPERATORS[meta["fieldtype"]]}
		for name, meta in FIELDS.items()
	]


@frappe.whitelist()
def create_segment(data):
	return (
		frappe.get_doc({"doctype": "CRM Segment", **service.payload(data, service.EDITABLE)})
		.insert()
		.as_dict()
	)


@frappe.whitelist()
def update_segment(name, data, expected_revision):
	doc = service.locked("CRM Segment", name, expected_revision)
	doc.update(service.payload(data, service.EDITABLE))
	return doc.save(ignore_version=False).as_dict()


@frappe.whitelist()
def transition_segment(name, status, expected_revision):
	return service.transition(name, status, expected_revision)


@frappe.whitelist()
def get_segment(name):
	doc = frappe.get_doc("CRM Segment", name)
	doc.check_permission("read")
	return doc.as_dict()


@frappe.whitelist()
def list_segments(status=None, category=None, start=0, page_length=20):
	filters = {k: v for k, v in {"status": status, "category": category}.items() if v}
	start = integer(start, "start")
	page_length = integer(page_length, "page_length", maximum=100) or 20
	segments = frappe.get_list(
		"CRM Segment",
		filters=filters,
		fields=[
			"name",
			"segment_code",
			"title",
			"purpose",
			"filters",
			"status",
			"category",
			"segment_type",
			"responsible_user",
			"revision",
			"owner",
			"creation",
			"modified",
		],
		order_by="modified desc, name asc",
		limit_start=start,
		limit_page_length=page_length,
	)
	for segment in segments:
		segment["member_count"] = (
			service.preview(segment=segment["name"], start=0, page_length=1)["total"]
			if segment.get("filters")
			else 0
		)
	return segments


@frappe.whitelist()
def preview_segment(segment=None, filters=None, start=0, page_length=20):
	return service.preview(segment, filters, start, page_length)


@frappe.whitelist()
def delete_segment(name, expected_revision):
	service.locked("CRM Segment", name, expected_revision)
	frappe.delete_doc("CRM Segment", name)
	return {"name": name, "deleted": True}
