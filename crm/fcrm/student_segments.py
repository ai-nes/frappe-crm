"""Permission-scoped group queries and transactional lifecycle commands."""

import frappe

from crm.fcrm.segment_lifecycle import lifecycle_command
from crm.fcrm.segment_rules import fail, integer, scoped_rule_query, student_scope_or_filters

MAX_SNAPSHOT = 10000
EDITABLE = {"title", "purpose", "responsible_user", "segment_type", "category", "is_public", "filters"}


def visible_student_query():
	return frappe.get_list(
		"CRM Student",
		fields=["name"],
		or_filters=student_scope_or_filters(),
		order_by="",
		limit_page_length=0,
		run=False,
	)


def visible_student_count():
	return frappe.db.sql(f"SELECT COUNT(*) FROM ({visible_student_query()}) visible_students")[0][0]


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
			scope = visible_student_query()
			return (
				f"SELECT allowed.name FROM ({scope}) allowed INNER JOIN `tabCRM Segment Member` m "
				f"ON m.student = allowed.name WHERE m.segment = {frappe.db.escape(doc.name)}"
			)
		filters = doc.filters
	return scoped_rule_query(filters)


def member_names(doc):
	query = membership_query(doc)
	return [row[0] for row in frappe.db.sql(query)]


def member_count(doc):
	"""Return the permission-scoped audience size for a saved Segment."""
	if not doc.get("filters") and not (doc.segment_type == "static" and doc.snapshot_at):
		return 0
	query = membership_query(doc)
	return frappe.db.sql(f"SELECT COUNT(*) FROM ({query}) members")[0][0]


def _student_search_query(query, search):
	"""Restrict an already permission-scoped membership query by Student text."""
	like = frappe.db.escape(f"%{search}%")
	search_fields = ("name", "full_name", "phone", "high_school", "major", "assigned_to")
	conditions = " OR ".join(f"student.{field} LIKE {like}" for field in search_fields)
	return (
		f"SELECT members.name FROM ({query}) members "
		f"INNER JOIN `tabCRM Student` student ON student.name = members.name "
		f"WHERE {conditions}"
	)


def preview(segment=None, filters=None, start=0, page_length=20, search=None):
	start = integer(start, "start")
	page_length = integer(page_length, "page_length", maximum=100)
	if not page_length:
		fail("page_length must be positive.")
	if bool(segment) == bool(filters):
		fail("Provide either a saved segment or draft filters.")
	search = str(search or "").strip()
	if len(search) > 140:
		fail("search must be 140 characters or fewer.")
	doc = frappe.get_doc("CRM Segment", segment) if segment else None
	membership = membership_query(doc, filters)
	member_count = None
	if search:
		member_count = frappe.db.sql(f"SELECT COUNT(*) FROM ({membership}) members")[0][0]
	query = _student_search_query(membership, search) if search else membership
	total = frappe.db.sql(f"SELECT COUNT(*) FROM ({query}) members")[0][0]
	member_count = total if member_count is None else member_count
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
			fields=[
				"name",
				"full_name",
				"phone",
				"student_stage",
				"major",
				"assigned_to",
				"potential",
				"intent",
			],
			order_by="name asc",
			limit_page_length=page_length,
		)
		if names
		else []
	)
	return {
		"total": total,
		"member_count": member_count,
		"total_students": visible_student_count(),
		"start": start,
		"page_length": page_length,
		"students": students,
	}


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
