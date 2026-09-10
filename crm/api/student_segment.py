import frappe

from crm.fcrm import student_segments as service
from crm.fcrm.segment_rules import FIELDS, OPERATORS, fail, integer

ANALYSIS_STATUSES = ("active", "inactive", "archive", "draft")
ANALYSIS_SEGMENT_FIELDS = [
	"name",
	"segment_code",
	"title",
	"purpose",
	"status",
	"category",
	"segment_type",
	"responsible_user",
	"revision",
	"owner",
	"creation",
	"modified",
]


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
def get_segment_by_code(segment_code):
	segment_code = str(segment_code or "").strip()
	if not segment_code:
		frappe.throw("segment_code is required.", frappe.ValidationError)

	segments = frappe.get_list(
		"CRM Segment",
		filters={"segment_code": segment_code},
		fields=["name"],
		limit_page_length=1,
	)
	if not segments:
		frappe.throw("Segment not found.", frappe.DoesNotExistError)

	return get_segment(segments[0]["name"])


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


def _analysis_segment_record(segment, member_count):
	return {
		"name": segment["name"],
		"segment_code": segment.get("segment_code") or segment["name"],
		"title": segment.get("title") or segment["name"],
		"purpose": segment.get("purpose"),
		"status": segment.get("status"),
		"category": segment.get("category"),
		"segment_type": segment.get("segment_type"),
		"responsible_user": segment.get("responsible_user"),
		"revision": int(segment.get("revision") or 0),
		"owner": segment.get("owner"),
		"creation": segment.get("creation"),
		"modified": segment.get("modified"),
		"member_count": int(member_count),
		# There is no durable membership-count history in the current schema.
		"member_change_7d": None,
	}


def _selected_segment_codes(value):
	if value in (None, "", []):
		return []
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except ValueError:
			fail("selected_segment_codes must be a JSON array.")
	if not isinstance(value, list):
		fail("selected_segment_codes must be a JSON array.")

	codes = []
	for code in value:
		if not isinstance(code, str) or not code.strip():
			fail("selected_segment_codes must contain non-empty strings.")
		code = code.strip()
		if code not in codes:
			codes.append(code)
	if len(codes) > 5:
		fail("Select at most 5 segments for overlap analysis.")
	return codes


def _analysis_segments():
	rows = frappe.get_list(
		"CRM Segment",
		fields=ANALYSIS_SEGMENT_FIELDS,
		order_by="modified desc, name asc",
		limit_page_length=0,
	)
	records = []
	docs_by_code = {}
	for row in rows:
		doc = frappe.get_doc("CRM Segment", row["name"])
		code = row.get("segment_code") or row["name"]
		member_count = service.member_count(doc)
		record = _analysis_segment_record(row, member_count)
		records.append(record)
		docs_by_code[code] = doc
	return records, docs_by_code


def _overlap_cells(selected, docs_by_code):
	queries = {
		segment["segment_code"]: service.membership_query(
			docs_by_code[segment["segment_code"]]
		)
		for segment in selected
	}
	counts = {}
	for row_index, row_segment in enumerate(selected):
		for column_index, column_segment in enumerate(selected):
			pair = tuple(sorted((row_index, column_index)))
			if pair not in counts:
				if row_index == column_index:
					counts[pair] = row_segment["member_count"]
				else:
					row_query = queries[row_segment["segment_code"]]
					column_query = queries[column_segment["segment_code"]]
					counts[pair] = frappe.db.sql(
						f"SELECT COUNT(*) FROM ({row_query}) row_members "
						f"INNER JOIN ({column_query}) column_members "
						"ON column_members.name = row_members.name"
					)[0][0]
			yield {
				"row_segment_code": row_segment["segment_code"],
				"column_segment_code": column_segment["segment_code"],
				"count": int(counts[pair]),
			}


@frappe.whitelist()
def get_segment_analysis(selected_segment_codes=None):
	"""Return permission-scoped summary and overlap data for Segment analysis."""
	frappe.has_permission("CRM Segment", "read", throw=True)
	selected_codes = _selected_segment_codes(selected_segment_codes)
	segments, docs_by_code = _analysis_segments()
	segments_by_code = {segment["segment_code"]: segment for segment in segments}

	selected = []
	for code in selected_codes:
		segment = segments_by_code.get(code)
		if not segment:
			frappe.throw("Segment not found or not permitted.", frappe.DoesNotExistError)
		selected.append(segment)

	summary = {status: 0 for status in ANALYSIS_STATUSES}
	for segment in segments:
		status = segment["status"]
		if status in summary:
			summary[status] += 1
	summary["total"] = len(segments)

	return {
		"summary": summary,
		"segments": segments,
		"selected_segments": selected,
		"overlap": {"cells": list(_overlap_cells(selected, docs_by_code))},
		"attention": [
			segment
			for segment in segments
			if segment["status"] == "active" and segment["member_count"] == 0
		],
	}


@frappe.whitelist()
def preview_segment(segment=None, filters=None, start=0, page_length=20):
	return service.preview(segment, filters, start, page_length)


@frappe.whitelist()
def delete_segment(name, expected_revision):
	service.locked("CRM Segment", name, expected_revision)
	frappe.delete_doc("CRM Segment", name)
	return {"name": name, "deleted": True}
