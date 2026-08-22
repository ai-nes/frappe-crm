"""Phase 4: creates CRM Interaction records from the source events the
admissions operating model considers meaningful lead touchpoints -- outgoing/
incoming Communication, a completed Task, a Call Log entry, a CRM Contact
lifecycle/assignment change, and a Consent Event. Each dispatcher below is
wired via hooks.py doc_events and fires only on the specific has_value_changed
transition listed in the guard table in
plans/260822-admissions-crm-alignment/phase-04-interaction-standard.md -- do
not loosen these into a generic "on every save" check.

Event Participation (Phase 5, not yet implemented) is intentionally not wired
here -- add its dispatcher once that doctype exists.
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
	interaction.insert(ignore_permissions=True)
	return interaction.name


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
	if doc.is_new():
		return
	if not (doc.has_value_changed("status") and doc.status == "Done"):
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
	if doc.is_new():
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
