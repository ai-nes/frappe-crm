"""Permission-scoped group queries and transactional lifecycle commands."""

import frappe

from crm.fcrm.segment_lifecycle import lifecycle_command
from crm.fcrm.segment_rules import fail, integer, scoped_rule_query

MAX_SNAPSHOT = 10000
EDITABLE = {"title", "purpose", "responsible_user", "segment_type", "category", "is_public", "filters"}


def payload(value, allowed):
	if isinstance(value, str):
		if len(value) > 70000:
			fail("Payload too large.")
		try:
			value = frappe.parse_json(value)
		except ValueError:
			fail("Invalid JSON payload.")
	if not isinstance(value, dict) or set(value) - allowed:
		fail("Payload contains unsupported fields.")
	return value


def locked(doctype, name, expected_revision):
	doc = frappe.get_doc(doctype, name, for_update=True)
	doc.check_permission("write")
	if int(doc.revision or 0) != integer(expected_revision, "expected_revision"):
		fail("Record changed; reload before retrying.", "REVISION_CONFLICT")
	return doc


def membership_query(doc=None, filters=None):
	if doc:
		doc.check_permission("read")
		if doc.segment_type == "static" and doc.snapshot_at:
			scope = frappe.get_list(
				"CRM Student", fields=["name"], order_by="", limit_page_length=0, run=False
			)
			return (
				f"SELECT allowed.name FROM ({scope}) allowed INNER JOIN `tabCRM Segment Member` m "
				f"ON m.student = allowed.name WHERE m.segment = {frappe.db.escape(doc.name)}"
			)
		filters = doc.filters
	return scoped_rule_query(filters)


def member_names(doc):
	query = membership_query(doc)
	return [row[0] for row in frappe.db.sql(query)]


def preview(segment=None, filters=None, start=0, page_length=20):
	start = integer(start, "start")
	page_length = integer(page_length, "page_length", maximum=100)
	if not page_length:
		fail("page_length must be positive.")
	if bool(segment) == bool(filters):
		fail("Provide either a saved segment or draft filters.")
	doc = frappe.get_doc("CRM Segment", segment) if segment else None
	query = membership_query(doc, filters)
	total = frappe.db.sql(f"SELECT COUNT(*) FROM ({query}) members")[0][0]
	names = [
		r[0]
		for r in frappe.db.sql(
			f"SELECT name FROM ({query}) members ORDER BY name LIMIT {page_length} OFFSET {start}"
		)
	]
	students = (
		frappe.get_list(
			"CRM Student",
			filters={"name": ["in", names]},
			fields=["name", "full_name", "enrollment_status", "potential", "intent"],
			order_by="name asc",
			limit_page_length=page_length,
		)
		if names
		else []
	)
	return {"total": total, "start": start, "page_length": page_length, "students": students}


def transition(name, status, expected_revision):
	doc = locked("CRM Segment", name, expected_revision)
	from crm.fcrm.segment_lifecycle import TRANSITIONS

	if status not in TRANSITIONS.get(doc.status, ()):
		fail("This status transition is not allowed.", "INVALID_TRANSITION")
	frappe.db.savepoint("segment_transition")
	try:
		with lifecycle_command():
			if status == "active" and doc.segment_type == "static" and not doc.snapshot_at:
				query = membership_query(doc)
				rows = frappe.db.sql(f"SELECT name FROM ({query}) members LIMIT {MAX_SNAPSHOT + 1}")
				if len(rows) > MAX_SNAPSHOT:
					fail(f"Static snapshot exceeds {MAX_SNAPSHOT} Students.")
				for (student,) in rows:
					frappe.get_doc(
						{"doctype": "CRM Segment Member", "segment": doc.name, "student": student}
					).insert(ignore_permissions=True)
				doc.snapshot_at = frappe.utils.now_datetime()
				doc.snapshot_by = frappe.session.user
			doc.status = status
			doc.save(ignore_version=False)
	except Exception:
		frappe.db.rollback(save_point="segment_transition")
		raise
	return doc.as_dict()
