import frappe
from frappe import _

from crm.fcrm.segment_rules import FIELDS as ALLOWED_SEGMENT_FIELDS
from crm.fcrm.segment_rules import MAX_CONDITIONS as MAX_CONDITIONS_PER_GROUP
from crm.fcrm.segment_rules import MAX_GROUPS, fail, validate_filters
from crm.fcrm.segment_rules import OPERATORS as OPERATORS_BY_FIELDTYPE
from crm.fcrm.student_attribution import record_campaign_touchpoint
from crm.fcrm.student_contact_conversion import students_for_contact
from crm.fcrm.student_segments import member_names, membership_query, preview

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
	return validate_filters(filters)


def get_matching_contact_names(filters):
	return {row[0] for row in frappe.db.sql(membership_query(filters=filters))}


@frappe.whitelist()
def get_segment_fields():
	"""Approved condition field list for the frontend condition picker — same
	source of truth the backend validator uses, so the two can't drift."""
	return get_segment_condition_fields()


@frappe.whitelist()
def preview_segment(segment=None, filters=None, start=0, page_length=20):
	result = preview(segment, filters, start, min(frappe.utils.cint(page_length) or 20, 100))
	names = [row["name"] for row in result.pop("students")]
	result["contacts"] = (
		frappe.get_list(
			"CRM Student",
			filters={"name": ["in", names]},
			fields=PREVIEW_CONTACT_FIELDS,
			order_by="name asc",
			limit_page_length=100,
		)
		if names
		else []
	)
	return result


@frappe.whitelist()
def attach_segment_to_campaign(segment, campaign):
	"""One-time snapshot: creates a 'Segment'-sourced Touchpoint for every
	contact the segment currently matches that doesn't already have a
	touchpoint for this campaign. Never re-evaluated later — editing the
	segment afterward has no effect on rows already created here. Batched so
	a single failing row only rolls back its own batch; earlier committed
	batches and the idempotency guard make re-running safe."""
	segment_doc = frappe.get_doc("CRM Segment", segment, for_update=True)
	segment_doc.check_permission("read")
	frappe.get_doc("CRM Campaign", campaign).check_permission("write")

	if segment_doc.status != "active":
		fail("Only active segments can be attached to a campaign.", "INVALID_TRANSITION")
	matches = sorted(member_names(segment_doc))

	existing_by_contact = {}
	if matches:
		engagement_rows = frappe.db.get_all(
			"CRM Marketing Engagement",
			filters={
				"engagement_kind": "campaign_touch",
				"crm_campaign": campaign,
				"crm_contact": ["in", matches],
			},
			fields=["crm_contact", "source", "crm_segment"],
		)
		for row in engagement_rows:
			existing_by_contact[row.crm_contact] = row
	contact_students = {contact: next(iter(students_for_contact(contact)), None) for contact in matches}

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
			current = frappe.get_doc("CRM Segment", segment, for_update=True)
			current.check_permission("read")
			frappe.get_doc("CRM Campaign", campaign).check_permission("write")
			if current.status != "active" or current.revision != segment_doc.revision:
				fail("Segment changed during attachment; retry with current rules.", "REVISION_CONFLICT")
			visible = set(
				frappe.get_list(
					"CRM Student", filters={"name": ["in", batch]}, pluck="name", limit_page_length=0
				)
			)
			if visible != set(batch):
				fail("Student scope changed during attachment.", "FORBIDDEN", permission=True)
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
