import frappe
from frappe import _

from crm.fcrm.student_attribution import record_campaign_touchpoint
from crm.fcrm.student_contact_conversion import students_for_contact

# Single source of truth for which CRM Contact fields a Segment condition may
# target. Every consumer (doctype validate, draft preview, saved preview,
# attach) must route through validate_segment_filters()/get_matching_contact_names()
# below so the allow-list can never be bypassed by a caller that skips
# Document.validate() (e.g. draft preview).
ALLOWED_SEGMENT_FIELDS = {
	"lifecycle_stage": {
		"label": "Lifecycle Stage",
		"fieldtype": "Select",
		"options": "Lead\nMQL\nApplicant\nEnrolled\nLost",
	},
	"source": {"label": "Source", "fieldtype": "Link", "options": "CRM Lead Source"},
	"platform": {"label": "Platform", "fieldtype": "Link", "options": "CRM Platform"},
	"branch": {"label": "Branch", "fieldtype": "Link", "options": "CRM Campus"},
	"province": {"label": "Province", "fieldtype": "Link", "options": "CRM Province"},
	"quality_bucket": {
		"label": "Lead Quality Bucket",
		"fieldtype": "Select",
		"options": "Hot\nWarm\nCool\nSai số\nKhông liên lạc được\nKhông quan tâm",
	},
	"is_opted_out": {"label": "Opted Out", "fieldtype": "Check"},
}

OPERATORS_BY_FIELDTYPE = {
	"Select": ("=", "!=", "in", "not in"),
	"Link": ("=", "!=", "in", "not in"),
	"Check": ("=", "!="),
}

MAX_GROUPS = 10
MAX_CONDITIONS_PER_GROUP = 20
DEFAULT_PREVIEW_PAGE_LENGTH = 20
MAX_PREVIEW_PAGE_LENGTH = 100
ATTACH_BATCH_SIZE = 500

PREVIEW_CONTACT_FIELDS = [
	"name",
	"full_name",
	"phone",
	"email",
	"lifecycle_stage",
	"source",
	"platform",
	"branch",
	"province",
	"quality_bucket",
	"is_opted_out",
	"modified",
]


def get_segment_condition_fields():
	"""Approved field list, exposed so the frontend condition picker and the
	backend validator always agree on what's allowed."""
	return [{"fieldname": fieldname, **meta} for fieldname, meta in ALLOWED_SEGMENT_FIELDS.items()]


def validate_segment_filters(filters):
	"""Raises frappe.throw on anything invalid. This is the single gate every
	consumer of Segment rules must call before touching CRM Contact data.

	Returns the normalized dict — callers must use the return value, since the
	"filters" JSON field round-trips as a string (not a dict) once a Segment
	doc is loaded from the database rather than freshly constructed."""
	if isinstance(filters, str):
		try:
			filters = frappe.parse_json(filters)
		except Exception:
			frappe.throw(_("Segment filters must be valid JSON."))

	if not isinstance(filters, dict):
		frappe.throw(_("Segment filters must be a JSON object with a 'groups' list."))

	groups = filters.get("groups")
	if not groups or not isinstance(groups, list):
		frappe.throw(_("Segment must include at least one filter group."))

	if len(groups) > MAX_GROUPS:
		frappe.throw(_("A Segment can have at most {0} filter groups.").format(MAX_GROUPS))

	for group in groups:
		if not isinstance(group, dict):
			frappe.throw(_("Each filter group must be a JSON object."))

		conditions = group.get("conditions")
		if not conditions or not isinstance(conditions, list):
			frappe.throw(_("Each filter group must include at least one condition."))

		if len(conditions) > MAX_CONDITIONS_PER_GROUP:
			frappe.throw(
				_("Each filter group can have at most {0} conditions.").format(MAX_CONDITIONS_PER_GROUP)
			)

		for condition in conditions:
			_validate_condition(condition)

	return filters


def _validate_condition(condition):
	if not isinstance(condition, dict):
		frappe.throw(_("Each condition must be a JSON object."))

	field = condition.get("field")
	operator = condition.get("operator")
	value = condition.get("value")

	if field not in ALLOWED_SEGMENT_FIELDS:
		frappe.throw(_("Field '{0}' is not allowed in Segment conditions.").format(field))

	fieldtype = ALLOWED_SEGMENT_FIELDS[field]["fieldtype"]
	allowed_operators = OPERATORS_BY_FIELDTYPE[fieldtype]

	if operator not in allowed_operators:
		frappe.throw(_("Operator '{0}' is not allowed for field '{1}'.").format(operator, field))

	if operator in ("in", "not in"):
		if not isinstance(value, list) or not value:
			frappe.throw(
				_("Operator '{0}' requires a non-empty list value for field '{1}'.").format(operator, field)
			)
	else:
		if value is None or value == "":
			frappe.throw(_("Condition on field '{0}' is missing a value.").format(field))
		if fieldtype == "Check" and value not in (0, 1, "0", "1", True, False):
			frappe.throw(_("Field '{0}' only accepts 0 or 1.").format(field))


def get_matching_contact_names(filters):
	"""OR-of-AND match: a contact qualifies if it satisfies every condition in
	at least one group. Validates first, so zero groups / a zero-condition
	group / a non-allow-listed field can never reach frappe.get_list — they
	are rejected outright rather than silently matching everyone."""
	filters = validate_segment_filters(filters)

	names = set()
	for group in filters["groups"]:
		group_filters = _group_to_query_filters(group["conditions"])
		names.update(frappe.get_list("CRM Contact", filters=group_filters, pluck="name", limit_page_length=0))

	return names


def _group_to_query_filters(conditions):
	# A group's "logic" key is round-tripped as-is but always treated as AND —
	# OR-within-a-group isn't supported (each group is itself the AND side of
	# the outer OR-of-AND model), so the key is currently unread here.
	return [[condition["field"], condition["operator"], condition["value"]] for condition in conditions]


@frappe.whitelist()
def get_segment_fields():
	"""Approved condition field list for the frontend condition picker — same
	source of truth the backend validator uses, so the two can't drift."""
	return get_segment_condition_fields()


@frappe.whitelist()
def preview_segment(segment=None, filters=None, start=0, page_length=20):
	"""Count + a page of CRM Contacts matching either a saved Segment (by name)
	or unsaved draft rules. Draft filters go through the exact same
	validate_segment_filters()/get_matching_contact_names() gate as a saved
	Segment, so allow-list rejection is identical on both paths."""
	start = frappe.utils.cint(start)
	page_length = min(frappe.utils.cint(page_length) or DEFAULT_PREVIEW_PAGE_LENGTH, MAX_PREVIEW_PAGE_LENGTH)

	if segment:
		doc = frappe.get_doc("CRM Segment", segment)
		doc.check_permission("read")
		filters_dict = doc.filters
	elif filters:
		filters_dict = frappe.parse_json(filters) if isinstance(filters, str) else filters
	else:
		frappe.throw(_("Provide either a saved segment name or draft filters to preview."))

	matches = sorted(get_matching_contact_names(filters_dict))
	total = len(matches)
	page_names = matches[start : start + page_length]

	contacts = (
		frappe.get_list(
			"CRM Contact",
			filters=[["name", "in", page_names]],
			fields=PREVIEW_CONTACT_FIELDS,
			order_by="name asc",
			limit_page_length=0,
		)
		if page_names
		else []
	)

	return {"total": total, "start": start, "page_length": page_length, "contacts": contacts}


@frappe.whitelist()
def attach_segment_to_campaign(segment, campaign):
	"""One-time snapshot: creates a 'Segment'-sourced Touchpoint for every
	contact the segment currently matches that doesn't already have a
	touchpoint for this campaign. Never re-evaluated later — editing the
	segment afterward has no effect on rows already created here. Batched so
	a single failing row only rolls back its own batch; earlier committed
	batches and the idempotency guard make re-running safe."""
	segment_doc = frappe.get_doc("CRM Segment", segment)
	segment_doc.check_permission("read")
	frappe.get_doc("CRM Campaign", campaign).check_permission("write")

	matches = sorted(get_matching_contact_names(segment_doc.filters))

	existing_by_contact = {}
	if matches:
		engagement_rows = frappe.db.get_all(
			"CRM Marketing Engagement",
			filters={"engagement_kind": "campaign_touch", "crm_campaign": campaign, "crm_contact": ["in", matches]},
			fields=["crm_contact", "source", "crm_segment"],
		)
		for row in engagement_rows:
			existing_by_contact[row.crm_contact] = row
	contact_students = {
		contact: next(iter(students_for_contact(contact)), None)
		for contact in matches
	}

	to_insert = []
	skipped_same_segment = 0
	skipped_other_source = 0
	skipped_unresolved_student = 0
	for contact in matches:
		existing_row = existing_by_contact.get(contact)
		if existing_row is None:
			to_insert.append(contact)
		elif existing_row.source == "Segment" and existing_row.crm_segment == segment_doc.name:
			skipped_same_segment += 1
		else:
			skipped_other_source += 1

	created = 0
	failed = False
	now = frappe.utils.now_datetime()
	for i in range(0, len(to_insert), ATTACH_BATCH_SIZE):
		batch = to_insert[i : i + ATTACH_BATCH_SIZE]
		try:
			for contact in batch:
				student = contact_students.get(contact)
				if not student:
					skipped_unresolved_student += 1
					continue
				# Runtime attribution writes must use the audited Student command,
				# with a stable key so retries cannot duplicate segment exposure.
				record_campaign_touchpoint(
					student=student,
					crm_campaign=campaign,
					crm_contact=contact,
					touched_at=now,
					source="Segment",
					crm_segment=segment_doc.name,
					idempotency_key=f"segment:{segment_doc.name}:{campaign}:{contact}",
					correlation_id=f"segment:{segment_doc.name}:{campaign}",
				)
			frappe.db.commit()
			created += len(batch) - sum(1 for contact in batch if not contact_students.get(contact))
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				title="CRM Segment attach batch failed",
				message=f"segment={segment_doc.name} campaign={campaign} batch_start={i} batch_size={len(batch)}",
			)
			failed = True
			break

	return {
		"total_matches": len(matches),
		"created": created,
		"skipped_same_segment": skipped_same_segment,
		"skipped_other_source": skipped_other_source,
		"skipped_unresolved_student": skipped_unresolved_student,
		"remaining": len(to_insert) - created,
		"failed": failed,
	}
