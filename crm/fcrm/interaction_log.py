"""Phase 4/5/6: creates CRM Interaction records from the source events the
admissions operating model considers meaningful lead touchpoints -- outgoing/
incoming Communication, a completed Task, a Call Log entry, a CRM Contact
lifecycle/assignment change, a Consent Event, a CRM Event Participation
status change (Phase 5), and a CRM Campaign Touchpoint insert (Phase 6, added
to satisfy the operating model's "no customer activity outside Interaction"
condition, which a bare Touchpoint insert previously violated). Each
dispatcher below is wired via hooks.py doc_events and fires only on the
specific has_value_changed transition listed in the guard tables in
plans/260822-admissions-crm-alignment/phase-04-interaction-standard.md and
phase-05-campaign-event-overhaul.md -- do not loosen these into a generic
"on every save" check.

Dispatchers are skipped while `frappe.flags.in_patch` is set, so migration
patches that backfill historical records (e.g. converting existing singular
CRM Contact campaign/event fields into CRM Campaign Touchpoint / CRM Event
Participation rows) don't flood the interaction timeline with
present-dated interactions for years-old activity.
"""

import frappe

CONSENT_EVENT_TO_INTERACTION_TYPE = {
	"Opted Out": "Opt-out",
	"Re-subscribed": "Opt-in",
	"Bounced": "Bounce",
	"Suppressed": "Data Error",
	# "Marked Test" is intentionally excluded -- test records shouldn't pollute
	# lead history with interactions.
}

EVENT_PARTICIPATION_STATUS_TO_INTERACTION_TYPE = {
	"Checked-in": "Checked-in",
	"No-show": "No-show",
	"Feedback Given": "Feedback",
	# "Registered" is handled separately in create_interaction_from_event_participation_insert,
	# since it's the doc's initial state rather than a has_value_changed transition.
}

SLA_SOURCE_DOCTYPES = {"Call Log", "Communication", "Task", "CRM Event Participation", "WhatsApp Message"}


def _source_matches_student(doctype, name, student, seen=None):
	"""Resolve provenance through the source's canonical Student/Contact link."""
	try:
		if not doctype or not name or not frappe.db.exists(doctype, name):
			return False
	except Exception:
		return False
	seen = seen or set()
	key = (doctype, name)
	if key in seen:
		return False
	seen.add(key)
	doc = frappe.get_doc(doctype, name)
	if getattr(doc, "student", None):
		return doc.student == student
	for fieldname in ("crm_contact", "contact", "customer", "party"):
		contact = getattr(doc, fieldname, None)
		if contact and frappe.db.exists("CRM Contact", contact):
			return frappe.db.get_value("CRM Contact", contact, "student") == student
	ref_doctype = getattr(doc, "reference_doctype", None)
	ref_name = getattr(doc, "reference_docname", None) or getattr(doc, "reference_name", None)
	if ref_doctype and ref_name:
		return _source_matches_student(ref_doctype, ref_name, student, seen)
	for row in getattr(doc, "links", None) or []:
		link_doctype = getattr(row, "link_doctype", None) or getattr(row, "doctype", None)
		link_name = getattr(row, "link_name", None) or getattr(row, "name", None)
		if link_doctype and link_name and _source_matches_student(link_doctype, link_name, student, seen):
			return True
	return False


def _source_is_actionable(doctype, doc):
	"""Require a completed/real source event, not an arbitrary reference string."""
	if doctype == "Call Log":
		return doc.status == "Completed" and bool(doc.duration or doc.end_time)
	if doctype == "Task":
		return doc.status == "Done"
	if doctype == "CRM Event Participation":
		return doc.status in {"Checked-in", "Feedback Given"}
	if doctype == "Communication":
		return doc.sent_or_received in {"Sent", "Received"}
	if doctype == "WhatsApp Message":
		return getattr(doc, "status", None) in {"Sent", "Delivered", "Read", "Received", "Completed"}
	return False


def verify_sla_source(doctype, name, student):
	try:
		if doctype not in SLA_SOURCE_DOCTYPES or not name or not frappe.db.exists(doctype, name):
			return False
		doc = frappe.get_doc(doctype, name)
		return _source_is_actionable(doctype, doc) and _source_matches_student(doctype, name, student)
	except Exception:
		return False


def create_interaction(
	*,
	interaction_type,
	student=None,
	crm_contact=None,
	reference_doctype=None,
	reference_docname=None,
	actor=None,
	summary=None,
	outcome=None,
):
	if not student and crm_contact:
		student = frappe.db.get_value("CRM Contact", crm_contact, "student")

	if not student and not crm_contact:
		return None

	if not frappe.db.exists("CRM Interaction Type", interaction_type):
		frappe.log_error(title=f"Unknown CRM Interaction Type: {interaction_type}")
		return None

	interaction = frappe.new_doc("CRM Interaction")
	interaction.student = student
	interaction.crm_contact = crm_contact
	interaction.interaction_type = interaction_type
	interaction.reference_doctype = reference_doctype
	interaction.reference_docname = reference_docname
	interaction.actor = actor or frappe.session.user
	interaction.summary = summary or interaction_type
	interaction.outcome = outcome
	if student and verify_sla_source(reference_doctype, reference_docname, student):
		interaction.source_verified = 1
	previous_flag = getattr(frappe.flags, "student_sla_source_service", False)
	frappe.flags.student_sla_source_service = True
	try:
		interaction.insert(ignore_permissions=True)
	finally:
		frappe.flags.student_sla_source_service = previous_flag
	return interaction.name


def satisfy_student_sla_from_interaction(doc, method=None):
	"""Close an eligible Student SLA once a source interaction has an outcome."""
	if not doc.get("student"):
		return None
	if doc.get("outcome") not in {"Captured", "Follow Up Needed", "Resolved", "Converted"}:
		return None
	if doc.get("reference_doctype") not in {"Call Log", "Communication", "Task", "CRM Event Participation", "WhatsApp Message"}:
		return None
	if not doc.get("source_verified") or not verify_sla_source(doc.reference_doctype, doc.reference_docname, doc.student):
		return None
	from crm.fcrm.student_sla import get_student_sla_status, record_qualifying_response

	status = get_student_sla_status(doc.student)
	attempt = status.get("attempt")
	if not attempt:
		return None
	try:
		return record_qualifying_response(
			attempt["attempt"], doc.name, expected_revision=attempt["revision"]
		)
	except Exception:
		# An out-of-scope/system-generated interaction remains evidence but cannot
		# satisfy the clock; the interaction write itself must not fail.
		return None


def _create_interaction_for_reference(
	reference_doctype, reference_name, interaction_type, source_doc, summary=None, actor=None, outcome=None
):
	if reference_doctype == "CRM Student":
		student, crm_contact = reference_name, None
	elif reference_doctype == "CRM Contact":
		crm_contact = reference_name
		student = frappe.db.get_value("CRM Contact", reference_name, "student")
	else:
		return None

	return create_interaction(
		interaction_type=interaction_type,
		student=student,
		crm_contact=crm_contact,
		reference_doctype=source_doc.doctype,
		reference_docname=source_doc.name,
		actor=actor,
		summary=summary,
		outcome=outcome,
	)


def create_interaction_from_communication_insert(doc, method=None):
	if doc.sent_or_received != "Sent":
		return
	if doc.reference_doctype not in ("CRM Contact", "CRM Student"):
		return
	try:
		_create_interaction_for_reference(
			doc.reference_doctype, doc.reference_name, "Outreach", doc, summary=doc.subject
		)
	except Exception:
		frappe.log_error(title="CRM Interaction creation failed (Communication insert)")


def create_interaction_from_communication_update(doc, method=None):
	if doc.reference_doctype not in ("CRM Contact", "CRM Student"):
		return

	is_reply = doc.sent_or_received == "Received" and doc.has_value_changed("sent_or_received")
	if not is_reply:
		return

	try:
		_create_interaction_for_reference(
			doc.reference_doctype, doc.reference_name, "Connected", doc, summary=doc.subject
		)
	except Exception:
		frappe.log_error(title="CRM Interaction creation failed (Communication update)")


def create_interaction_from_task_update(doc, method=None):
	# on_update fires during insert too, at a point where is_new() has already
	# flipped to False but flags.in_insert is still True -- check both, or a
	# freshly-inserted doc's baseline-less has_value_changed() (always True)
	# fires spuriously.
	if doc.is_new() or doc.flags.in_insert:
		return
	if not (doc.has_value_changed("status") and doc.status == "Done"):
		return
	# A Phase 5 next-action Task may already be linked to the canonical
	# Interaction that recorded its outcome. Completion must satisfy that event,
	# not create a second timeline row.
	if getattr(doc, "linked_interaction", None):
		return
	if not doc.description:
		return
	if doc.reference_doctype not in ("CRM Contact", "CRM Student"):
		return

	try:
		_create_interaction_for_reference(
			doc.reference_doctype,
			doc.reference_docname,
			"Counseling",
			doc,
			summary=doc.title,
			actor=doc.assigned_to,
		)
	except Exception:
		frappe.log_error(title="CRM Interaction creation failed (Task update)")


def create_interaction_from_call_log_insert(doc, method=None):
	if doc.reference_doctype not in ("CRM Contact", "CRM Student"):
		return

	interaction_type = "Connected" if (doc.status == "Completed" and doc.duration) else "Outreach"
	try:
		_create_interaction_for_reference(
			doc.reference_doctype,
			doc.reference_docname,
			interaction_type,
			doc,
			summary=f"{doc.type} call ({doc.status})",
			actor=doc.caller or doc.receiver,
		)
	except Exception:
		frappe.log_error(title="CRM Interaction creation failed (Call Log insert)")


def create_interaction_from_contact_update(doc, method=None):
	# See create_interaction_from_task_update -- on_update fires during insert
	# too, after is_new() has already flipped to False; flags.in_insert is the
	# reliable signal there.
	if doc.is_new() or doc.flags.in_insert:
		return

	if doc.has_value_changed("lifecycle_stage"):
		try:
			create_interaction(
				interaction_type="Stage Changed",
				crm_contact=doc.name,
				student=doc.student,
				reference_doctype="CRM Contact",
				reference_docname=doc.name,
				summary=f"Stage changed to {doc.lifecycle_stage}",
			)
		except Exception:
			frappe.log_error(title="CRM Interaction creation failed (Contact stage change)")

	if doc.has_value_changed("owner_staff"):
		before = doc.get_doc_before_save()
		was_unassigned = not (before.owner_staff if before else None)
		interaction_type = "Lead Assigned" if was_unassigned else "Lead Reassigned"
		try:
			create_interaction(
				interaction_type=interaction_type,
				crm_contact=doc.name,
				student=doc.student,
				reference_doctype="CRM Contact",
				reference_docname=doc.name,
				summary=f"{interaction_type}: {doc.owner_staff or 'Unassigned'}",
			)
		except Exception:
			frappe.log_error(title="CRM Interaction creation failed (Contact assignment change)")


def create_interaction_from_consent_event(doc, method=None):
	interaction_type = CONSENT_EVENT_TO_INTERACTION_TYPE.get(doc.event_type)
	if not interaction_type:
		return

	try:
		create_interaction(
			interaction_type=interaction_type,
			crm_contact=doc.contact,
			reference_doctype="CRM Contact Consent Event",
			reference_docname=doc.name,
			actor=doc.created_by,
			summary=f"{doc.event_type} ({doc.source or 'system'})",
		)
	except Exception:
		frappe.log_error(title="CRM Interaction creation failed (Consent event)")


def create_interaction_from_event_participation_insert(doc, method=None):
	if frappe.flags.in_patch:
		return

	try:
		create_interaction(
			interaction_type="Registered",
			crm_contact=doc.crm_contact,
			student=doc.student,
			reference_doctype=doc.doctype,
			reference_docname=doc.name,
			actor=doc.actor,
			summary=f"Registered for {doc.crm_event}",
		)
	except Exception:
		frappe.log_error(title="CRM Interaction creation failed (Event Participation insert)")


def create_interaction_from_event_participation_update(doc, method=None):
	if frappe.flags.in_patch:
		return
	# See create_interaction_from_task_update -- on_update fires during insert
	# too, after is_new() has already flipped to False; flags.in_insert is the
	# reliable signal there.
	if doc.is_new() or doc.flags.in_insert:
		return
	if not doc.has_value_changed("status"):
		return

	interaction_type = EVENT_PARTICIPATION_STATUS_TO_INTERACTION_TYPE.get(doc.status)
	if not interaction_type:
		return

	try:
		create_interaction(
			interaction_type=interaction_type,
			crm_contact=doc.crm_contact,
			student=doc.student,
			reference_doctype=doc.doctype,
			reference_docname=doc.name,
			actor=doc.actor,
			summary=f"{interaction_type} at {doc.crm_event}",
		)
	except Exception:
		frappe.log_error(title="CRM Interaction creation failed (Event Participation update)")


def create_interaction_from_campaign_touchpoint_insert(doc, method=None):
	if frappe.flags.in_patch:
		return

	try:
		create_interaction(
			interaction_type="Campaign Touched",
			crm_contact=doc.crm_contact,
			student=doc.student,
			reference_doctype=doc.doctype,
			reference_docname=doc.name,
			summary=f"Touched by {doc.crm_campaign}",
		)
	except Exception:
		frappe.log_error(title="CRM Interaction creation failed (Campaign Touchpoint insert)")


def clear_interaction_reference(doc, method=None):
	"""on_trash hook (Communication/Task/Call Log/CRM Contact Consent Event):
	null out the dangling reference on any CRM Interaction that pointed at the
	source record being deleted. Interactions are a historical audit trail and
	must never be deleted themselves just because their source was."""
	frappe.db.sql(
		"""
		update `tabCRM Interaction`
		set reference_doctype = NULL, reference_docname = NULL
		where reference_doctype = %s and reference_docname = %s
		""",
		(doc.doctype, doc.name),
	)
