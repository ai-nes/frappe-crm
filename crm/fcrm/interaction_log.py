"""Creates CRM Interaction records from the source events the admissions
operating model considers meaningful lead touchpoints -- outgoing/incoming
Communication, a completed Task, a Call Log entry, a CRM Contact
lifecycle/assignment change, a Consent Event, and a CRM Marketing Engagement
insert/status change (added to satisfy the
operating model's "no customer activity outside Interaction" condition,
which a bare Touchpoint insert previously violated). Each dispatcher below
is wired via hooks.py doc_events and fires only on the specific
has_value_changed transition each guard checks explicitly -- do not loosen
these into a generic "on every save" check.

Dispatchers are skipped while `frappe.flags.in_patch` is set, so migration
patches that backfill historical records (e.g. converting existing singular
CRM Contact campaign/event fields into CRM Marketing Engagement rows) don't flood the interaction timeline with
present-dated interactions for years-old activity.
"""

import hashlib
import json

import frappe

from crm.fcrm.student_contact_conversion import contact_is_linked_to_student, students_for_contact

INTERACTION_CHANNEL_ALIASES = {
	"web": "webchat",
	"website": "webchat",
	"website_chat": "webchat",
	"web_chat": "webchat",
	"webchat": "webchat",
	"facebook_messenger": "facebook",
	"facebook": "facebook",
	"instagram": "instagram",
	"line": "line",
	"sms": "sms",
	"telegram": "telegram",
	"tiktok": "tiktok",
	"twitter": "twitter",
	"whatsapp": "whatsapp",
	"zalo": "zalo",
	"email": "email",
	"phone": "phone",
}
INTERACTION_DIRECTION_ALIASES = {
	"inbound": "inbound",
	"incoming": "inbound",
	"received": "inbound",
	"outbound": "outbound",
	"outgoing": "outbound",
	"sent": "outbound",
}
INTERACTION_AUTHORITY_FIELDS = frozenset(
	{
		"actor",
		"actor_user",
		"profile",
		"roles",
		"campus_scope",
		"team_scope",
		"capability",
		"signed",
		"owner_staff",
	}
)

CONSENT_EVENT_TO_INTERACTION_TYPE = {
	"Granted": "OPT_IN",
	"Opted Out": "OPT_OUT",
	"Re-subscribed": "OPT_IN",
	"Bounced": "BOUNCE",
	"Suppressed": "DATA_ERROR",
	# "Marked Test" is intentionally excluded -- test records shouldn't pollute
	# lead history with interactions.
}

EVENT_PARTICIPATION_STATUS_TO_INTERACTION_TYPE = {
	"Checked-in": "CHECKED_IN",
	"No-show": "NO_SHOW",
	"Feedback Given": "FEEDBACK",
	# "Registered" is handled by the canonical Marketing Engagement insert hook,
	# since it's the doc's initial state rather than a has_value_changed transition.
}

# A completed CRM Action Item is only a genuine parent/student touchpoint when
# its underlying CRM Action has a real contact channel; an internal action
# (default_channel NONE) never produces an Interaction.
ACTION_CHANNEL_TO_INTERACTION_TYPE = {
	"CALL": "PHONE_CALL",
	"EMAIL": "OUTREACH",
	"MESSAGE": "MESSAGE",
}

# CRM Action Item.outcome_code (7 admissions-specific values) mapped onto the
# CRM Interaction.outcome enum (7 generic CRM values). Deliberately not a
# 1:1 identity map -- the two vocabularies describe different things and stay
# separate; this is the one explicit, auditable translation between them.
ACTION_OUTCOME_TO_INTERACTION_OUTCOME = {
	"NO_RESPONSE": "No Response",
	"INTEREST_INCREASED": "Captured",
	"NEEDS_MORE_INFORMATION": "Follow Up Needed",
	"CALL_BACK_LATER": "Follow Up Needed",
	"APPLICATION_STARTED": "Resolved",
	"APPLICATION_COMPLETED": "Converted",
	"NOT_INTERESTED": "Resolved",
}

# Attribution is evidence, not an admissions engagement.  In particular, an
# event registration/check-in must not close Student SLA or create outcomes.
SLA_SOURCE_DOCTYPES = {"Call Log", "Communication", "Task", "WhatsApp Message"}

# CRM Contact is the enduring lead/contact entity itself, not a discrete source
# event -- create_interaction_from_contact_update reuses it as the reference
# for every lifecycle/assignment transition on that contact. Keying
# external_id off it would collapse distinct Stage Changed / Lead Assigned /
# Lead Reassigned events on the same contact into a single deduplicated row,
# destroying that history. Doctypes here never get an external_id.
NON_DEDUPABLE_REFERENCE_DOCTYPES = {"CRM Contact"}
MAX_EXTERNAL_INTERACTION_CONTENT_BYTES = 60_000
MAX_EXTERNAL_INTERACTION_TURNS = 200
CHATWOOT_INTERACTION_TYPE = "MESSAGE"


def external_id_for(reference_doctype, reference_docname, interaction_type):
	if not reference_doctype or not reference_docname or not interaction_type:
		return None
	if reference_doctype in NON_DEDUPABLE_REFERENCE_DOCTYPES:
		return None
	return f"{reference_doctype}:{reference_docname}:{interaction_type}"


def _interaction_fail(code: str, message: str):
	from crm.fcrm.student_intake import StudentIntakeError

	raise StudentIntakeError(code, message)


def _text(value):
	if value is None:
		return None
	value = str(value).strip()
	return value or None


def normalize_external_interaction_payload(payload: dict) -> dict:
	"""Validate and normalize the public interaction command shape."""
	if not isinstance(payload, dict):
		_interaction_fail("INVALID_INPUT", "Payload must be a JSON object.")
	for fieldname in INTERACTION_AUTHORITY_FIELDS:
		if fieldname in payload:
			_interaction_fail("INVALID_INPUT", f"{fieldname} is server-owned.")
	for fieldname in ("content", "raw_content", "transcript", "quoted_text"):
		if fieldname in payload:
			_interaction_fail("INVALID_INPUT", f"{fieldname} is retired; submit labelled turns instead.")

	source_namespace = _text(payload.get("source_namespace"))
	source_record_id = _text(payload.get("source_record_id"))
	idempotency_key = _text(payload.get("idempotency_key"))
	student_id = _text(payload.get("student_id"))
	contact_id = _text(payload.get("contact_id"))
	external_target_id = _text(payload.get("target_external_id"))
	if not source_namespace or not source_record_id or not idempotency_key:
		_interaction_fail(
			"INVALID_INPUT",
			"source_namespace, source_record_id and idempotency_key are required.",
		)
	if len(source_namespace) > 64 or len(source_record_id) > 120 or len(idempotency_key) > 140:
		_interaction_fail("INVALID_INPUT", "Interaction source identifiers exceed their size limits.")
	agent_id = _text(payload.get("agent_id"))
	conversation_id = _text(payload.get("conversation_id"))
	evidence_kind = _text(payload.get("evidence_kind")) or "message"
	evidence_state = _text(payload.get("evidence_state")) or "final"
	try:
		source_revision = int(payload.get("source_revision") or 1)
	except (TypeError, ValueError):
		_interaction_fail("INVALID_INPUT", "source_revision must be a positive integer.")
	if source_revision < 1 or isinstance(payload.get("source_revision"), bool):
		_interaction_fail("INVALID_INPUT", "source_revision must be a positive integer.")
	if evidence_kind not in {"message", "call"} or evidence_state not in {"draft", "final", "correction"}:
		_interaction_fail("INVALID_INPUT", "Evidence kind or state is invalid.")
	if evidence_state == "draft" and evidence_kind != "call":
		_interaction_fail("INVALID_INPUT", "Only calls may be draft evidence.")
	for fieldname, field_value in (("agent_id", agent_id), ("conversation_id", conversation_id)):
		if field_value and len(field_value) > 140:
			_interaction_fail("INVALID_INPUT", f"{fieldname} exceeds its size limit.")

	channel_key = _text(payload.get("channel"))
	direction_key = _text(payload.get("direction"))
	channel = INTERACTION_CHANNEL_ALIASES.get(
		(channel_key or "").casefold().replace("-", "_").replace(" ", "_")
	)
	direction = INTERACTION_DIRECTION_ALIASES.get((direction_key or "").casefold().replace("-", "_"))
	if not channel:
		_interaction_fail("INVALID_INPUT", "channel is not supported.")
	if not direction:
		_interaction_fail("INVALID_INPUT", "direction must be inbound or outbound.")

	turns = _normalize_external_turns(payload.get("turns"))
	occurred_at = payload.get("occurred_at")
	if not occurred_at:
		_interaction_fail("INVALID_INPUT", "occurred_at is required.")
	try:
		parsed_occurred_at = frappe.utils.get_datetime(occurred_at)
	except (TypeError, ValueError):
		_interaction_fail("INVALID_INPUT", "occurred_at must be a valid datetime.")
	if not parsed_occurred_at:
		_interaction_fail("INVALID_INPUT", "occurred_at must be a valid datetime.")
	occurred_at = str(parsed_occurred_at)

	if not student_id and not contact_id and not external_target_id:
		_interaction_fail("INVALID_INPUT", "A Student, Contact or external target is required.")
	if student_id and contact_id and student_id == contact_id:
		_interaction_fail("INVALID_INPUT", "Student and Contact targets are ambiguous.")
	return {
		"source_namespace": source_namespace,
		"source_record_id": source_record_id,
		"idempotency_key": idempotency_key,
		"student_id": student_id,
		"contact_id": contact_id,
		"target_external_id": external_target_id,
		"channel": channel,
		"direction": direction,
		"turns": turns,
		"occurred_at": occurred_at,
		"agent_id": agent_id,
		"conversation_id": conversation_id,
		"evidence_kind": evidence_kind,
		"evidence_state": evidence_state,
		"source_revision": source_revision,
	}


def _source_matches_student(doctype, name, student, seen=None):
	"""Resolve provenance through the source's canonical Student/Contact link."""
	try:
		if not doctype or not name or not frappe.db.exists(doctype, name):
			return False
	except Exception:
		return False
	# A completed source may be linked directly to CRM Student. The name match is
	# the same canonical identity boundary used for a CRM Contact relationship.
	if doctype == "CRM Student":
		return name == student
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
			return contact_is_linked_to_student(contact, student)
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


def _interaction_target_matches(target: dict, student: str | None, contact: str | None) -> bool:
	return target.get("student") == student and target.get("contact") == contact


def _external_interaction_matches(record, target: dict, payload: dict) -> bool:
	value = record.get
	return (
		_interaction_target_matches(target, value("student"), value("crm_contact"))
		and _text(value("channel")) == payload["channel"]
		and _text(value("direction")) == payload["direction"]
		and _text(value("interaction_datetime")) == payload["occurred_at"]
		and _text(value("conversation_id")) == payload.get("conversation_id")
		and _text(value("agent_id")) == payload.get("agent_id")
	)


def _evidence_digest(content: str) -> str:
	return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _source_digest(turns: list[dict]) -> str:
	return hashlib.sha256(
		json.dumps(turns, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
	).hexdigest()


def _ensure_interaction_evidence(payload: dict, target: dict) -> list[str]:
	"""Persist one protected Evidence record for each labelled source turn."""
	base_key = f"{payload['source_namespace']}:{payload['source_record_id']}:{payload['source_revision']}"
	evidence_names = []
	for index, turn in enumerate(payload["turns"], start=1):
		key = base_key if len(payload["turns"]) == 1 else f"{base_key}:turn:{index}"
		digest = _evidence_digest(turn["content"])
		existing = frappe.db.get_value("CRM Interaction Evidence", {"external_event_key": key}, "name")
		if existing:
			stored = frappe.db.get_value("CRM Interaction Evidence", existing, "evidence_digest")
			if stored != digest:
				_interaction_fail(
					"IDEMPOTENCY_KEY_REUSED", "The evidence revision was reused with another body."
				)
			evidence_names.append(existing)
			continue
		evidence = frappe.get_doc(
			{
				"doctype": "CRM Interaction Evidence",
				"student": target.get("student"),
				"crm_contact": target.get("contact"),
				"external_event_key": key,
				"source_namespace": payload["source_namespace"],
				"source_record_id": payload["source_record_id"],
				"source_revision": payload["source_revision"],
				"evidence_digest": digest,
				"evidence_kind": payload["evidence_kind"],
				"evidence_state": payload["evidence_state"],
				"channel": payload["channel"],
				"direction": payload["direction"],
				"actor_role": turn["speaker_role"],
				"occurred_at": turn.get("occurred_at") or payload["occurred_at"],
				"content": turn["content"],
			}
		).insert(ignore_permissions=True)
		evidence_names.append(evidence.name)
	return evidence_names


def _ensure_interaction_analysis_run(
	interaction: str, episode_key: str, source_revision: int, source_digest: str
) -> str:
	"""Create the dedicated, revision-fenced run identity for a sealed episode."""
	run_key = hashlib.sha256(
		f"{interaction}:{episode_key}:{source_revision}:{source_digest}".encode()
	).hexdigest()
	existing = frappe.db.get_value("CRM Interaction Analysis Run", {"run_key": run_key}, "name")
	if not existing:
		existing = (
			frappe.get_doc(
				{
					"doctype": "CRM Interaction Analysis Run",
					"interaction": interaction,
					"episode_key": episode_key,
					"run_key": run_key,
					"source_revision": source_revision,
					"source_digest": source_digest,
					"status": "queued",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	stage_key = f"interaction-analysis:{run_key}"
	if not frappe.db.exists("CRM Analysis Run Stage", {"stage_key": stage_key}):
		frappe.get_doc(
			{
				"doctype": "CRM Analysis Run Stage",
				"parent_run_type": "CRM Interaction Analysis Run",
				"parent_run": existing,
				"stage_kind": "interaction_analysis",
				"stage_key": stage_key,
				"status": "queued",
				"stage_generation": 0,
				"expected_source_revision": str(source_revision),
				"expected_source_digest": source_digest,
			}
		).insert(ignore_permissions=True)
		if frappe.conf.get("crm_agents_interaction_analysis_events_enabled", 0) not in (0, "0", False):
			from crm.api.agent_events import record_agent_event

			run_doc = frappe.get_doc("CRM Interaction Analysis Run", existing)
			record_agent_event("interaction.analysis.requested.v1", run_doc)
	return existing


def read_interaction_evidence(interaction: str, *, expected_revision: int, expected_digest: str) -> dict:
	"""Return a revision's labelled raw turns only to the service identity."""
	service_user = frappe.conf.get("crm_agents_service_user")
	if not service_user or frappe.session.user != service_user:
		_interaction_fail("UNAUTHORIZED", "Evidence is restricted to the CRM-Agents capability.")
	parent = frappe.db.get_value(
		"CRM Interaction", interaction, ["source_revision", "evidence_digest"], as_dict=True
	)
	if (
		not parent
		or int(parent.source_revision or 0) != int(expected_revision)
		or parent.evidence_digest != expected_digest
	):
		_interaction_fail(
			"STALE_SOURCE_REVISION", "Evidence digest no longer matches the requested revision."
		)
	evidence_rows = frappe.get_all(
		"CRM Interaction Evidence",
		filters={"interaction": interaction, "source_revision": expected_revision},
		fields=["name", "actor_role", "content", "evidence_digest", "occurred_at"],
		order_by="occurred_at asc, creation asc, name asc",
	)
	if not evidence_rows:
		_interaction_fail("STALE_SOURCE_REVISION", "Evidence for the requested revision is unavailable.")
	return {
		"evidence_digest": expected_digest,
		"source_revision": expected_revision,
		"turns": [
			{
				"evidence_ref": {"doctype": "CRM Interaction Evidence", "name": row.name},
				"actor_role": row.actor_role,
				"content": row.content,
			}
			for row in evidence_rows
		],
	}


def _normalize_external_turns(value) -> list[dict]:
	"""Return bounded, speaker-labelled evidence turns.

	Every producer must label each turn. The source boundary never infers a
	speaker from interaction direction or accepts a legacy raw ``content`` body.
	"""
	if not isinstance(value, list) or not value or len(value) > MAX_EXTERNAL_INTERACTION_TURNS:
		_interaction_fail("INVALID_INPUT", "turns must be a bounded non-empty list.")
	turns = []
	for index, turn in enumerate(value):
		if not isinstance(turn, dict) or set(turn) - {"speaker_role", "content", "occurred_at"}:
			_interaction_fail("INVALID_INPUT", f"turns[{index}] has an unsupported shape.")
		role = _text(turn.get("speaker_role"))
		body = turn.get("content")
		if role not in {"student", "advisor", "system"}:
			_interaction_fail("INVALID_INPUT", f"turns[{index}].speaker_role is invalid.")
		if not isinstance(body, str) or not body.strip():
			_interaction_fail("INVALID_INPUT", f"turns[{index}].content is required.")
		if len(body.encode("utf-8")) > MAX_EXTERNAL_INTERACTION_CONTENT_BYTES:
			_interaction_fail("INVALID_INPUT", f"turns[{index}].content exceeds the interaction size limit.")
		occurred_at = _text(turn.get("occurred_at"))
		if occurred_at:
			try:
				occurred_at = str(frappe.utils.get_datetime(occurred_at))
			except (TypeError, ValueError):
				_interaction_fail("INVALID_INPUT", f"turns[{index}].occurred_at must be a valid datetime.")
		turns.append({"speaker_role": role, "content": body.strip(), "occurred_at": occurred_at})
	if len(json.dumps(turns, ensure_ascii=False).encode("utf-8")) > MAX_EXTERNAL_INTERACTION_CONTENT_BYTES:
		_interaction_fail("INVALID_INPUT", "turns exceed the interaction size limit.")
	return turns


def _external_target_matches(external_id: str) -> list[dict]:
	matches = []
	for doctype in ("CRM Student", "CRM Contact"):
		try:
			meta = frappe.get_meta(doctype)
			fieldnames = {field.fieldname for field in meta.fields}
		except Exception:
			continue
		for fieldname in ("import_source_id", "external_id", "external_source_id"):
			if fieldname not in fieldnames:
				continue
			try:
				rows = frappe.get_all(doctype, filters={fieldname: external_id}, pluck="name")
			except Exception:
				rows = []
			matches.extend({"doctype": doctype, "name": name} for name in rows)
	return list({(row["doctype"], row["name"]): row for row in matches}.values())


def _resolve_external_interaction_target(payload: dict) -> dict:
	student_id = _text(payload.get("student_id"))
	contact_id = _text(payload.get("contact_id"))
	external_target_id = _text(payload.get("target_external_id"))
	if student_id and not frappe.db.exists("CRM Student", student_id):
		_interaction_fail("INVALID_TARGET", "The target Student does not exist.")
	if contact_id and not frappe.db.exists("CRM Contact", contact_id):
		_interaction_fail("INVALID_TARGET", "The target Contact does not exist.")
	if student_id and contact_id:
		linked_students = students_for_contact(contact_id)
		if linked_students and student_id not in linked_students:
			_interaction_fail("AMBIGUOUS_TARGET", "Student and Contact resolve to different identities.")
		return {"student": student_id, "contact": contact_id}
	if student_id:
		return {"student": student_id, "contact": None}
	if contact_id:
		linked_students = students_for_contact(contact_id)
		if len(linked_students) > 1:
			_interaction_fail("AMBIGUOUS_TARGET", "The Contact is linked to multiple Students.")
		return {"student": linked_students[0] if linked_students else None, "contact": contact_id}
	if not external_target_id:
		_interaction_fail("INVALID_TARGET", "A target is required.")
	matches = _external_target_matches(external_target_id)
	if len(matches) != 1:
		_interaction_fail(
			"AMBIGUOUS_TARGET" if matches else "INVALID_TARGET",
			"The external target does not resolve to exactly one CRM record.",
		)
	match = matches[0]
	if match["doctype"] == "CRM Student":
		return {"student": match["name"], "contact": None}
	linked_students = students_for_contact(match["name"])
	if len(linked_students) > 1:
		_interaction_fail("AMBIGUOUS_TARGET", "The external Contact is linked to multiple Students.")
	return {"student": linked_students[0] if linked_students else None, "contact": match["name"]}


def _assert_interaction_scope(target: dict, authority: dict):
	if authority.get("profile") in {"platform_superuser", "admissions_director"} or authority.get(
		"scope_all"
	):
		return
	if target.get("student"):
		row = frappe.db.get_value(
			"CRM Student", target["student"], ["branch", "owning_team", "owner_staff"], as_dict=True
		)
	else:
		row = frappe.db.get_value(
			"CRM Contact", target.get("contact"), ["branch", "owning_team", "owner_staff"], as_dict=True
		)
	if not row:
		_interaction_fail("INVALID_TARGET", "The interaction target is no longer available.")
	campuses = set(authority.get("campus_scope") or [])
	teams = set(authority.get("team_scope") or [])
	if campuses and row.branch not in campuses:
		_interaction_fail("UNAUTHORIZED", "The interaction target is outside the current Campus scope.")
	if row.owning_team not in teams and row.owner_staff != authority.get("actor_staff"):
		_interaction_fail("UNAUTHORIZED", "The interaction target is outside the current Team scope.")


def ingest_external_interaction(payload: dict, *, signed_context: dict | None = None) -> dict:
	"""Create one scoped, idempotent interaction from an external message."""
	from crm.fcrm.student_intake import (
		INTERACTION_CAPABILITY,
		_assert_replay_scope,
		_persist_receipt,
		_receipt_replay,
		_resolve_authority,
		body_fingerprint,
		receipt_keys,
	)

	payload = normalize_external_interaction_payload(payload)
	authority = _resolve_authority(INTERACTION_CAPABILITY, signed_context=signed_context)
	target = _resolve_external_interaction_target(payload)
	_assert_interaction_scope(target, authority)
	interaction_type = CHATWOOT_INTERACTION_TYPE if payload["source_namespace"] == "chatwoot" else "MESSAGE"
	if not frappe.db.exists(
		"CRM Interaction Type", {"name": interaction_type, "enabled": 1}
	):
		_interaction_fail("CONFIGURATION_ERROR", f"Interaction type {interaction_type} is not configured.")
	external_id = f"{payload['source_namespace']}:{payload['source_record_id']}"
	if len(external_id) > 140:
		_interaction_fail("INVALID_INPUT", "The external interaction key exceeds its size limit.")
	keys = receipt_keys(
		payload["source_namespace"],
		payload["source_record_id"],
		payload["idempotency_key"],
		authority.get("actor_user") or payload["source_namespace"],
		command_kind="interaction",
		source_revision=payload["source_revision"],
	)
	fingerprint = body_fingerprint(payload)
	replay = _receipt_replay(
		keys,
		fingerprint,
		source_namespace=payload["source_namespace"],
		idempotency_key=payload["idempotency_key"],
	)
	if replay:
		_assert_replay_scope(replay, authority)
		return replay
	evidence_names = _ensure_interaction_evidence(payload, target)
	evidence_name = evidence_names[0]
	evidence_digest = _source_digest(payload["turns"])
	episode_key = (
		payload.get("conversation_id") or f"{payload['source_namespace']}:{payload['source_record_id']}"
	)
	episode_state = "open" if payload["evidence_state"] == "draft" else "sealed"

	existing = frappe.db.get_value(
		"CRM Interaction",
		{"external_id": external_id},
		[
			"name",
			"student",
			"crm_contact",
			"channel",
			"direction",
			"interaction_datetime",
			"conversation_id",
			"agent_id",
			"source_revision",
		],
		as_dict=True,
	)
	if existing:
		if not _external_interaction_matches(existing, target, payload):
			_interaction_fail(
				"IDEMPOTENCY_KEY_REUSED",
				"The external interaction key was already used with another message.",
			)
		interaction_name = existing.get("name")
		stored_revision = int(existing.get("source_revision") or 1)
		if payload["source_revision"] < stored_revision:
			_interaction_fail(
				"STALE_SOURCE_REVISION", "The interaction already has a newer evidence revision."
			)
		if payload["source_revision"] > stored_revision:
			frappe.db.set_value(
				"CRM Interaction",
				interaction_name,
				{
					"source_revision": payload["source_revision"],
					"evidence_digest": evidence_digest,
					"evidence": evidence_name,
					"episode_key": episode_key,
					"episode_state": episode_state,
				},
				update_modified=False,
			)
	else:
		interaction_name = create_interaction(
			interaction_type=interaction_type,
			student=target.get("student"),
			crm_contact=target.get("contact"),
			actor=authority.get("actor_user"),
			summary=f"{payload['channel']} {payload['direction']}",
			notes=None,
			interaction_datetime=payload["occurred_at"],
			channel=payload["channel"],
			direction=payload["direction"],
			conversation_id=payload.get("conversation_id"),
			agent_id=payload.get("agent_id"),
			source_namespace=payload["source_namespace"],
			source_record_id=payload["source_record_id"],
			external_id=external_id,
			source_revision=payload["source_revision"],
			evidence_digest=evidence_digest,
			evidence=evidence_name,
			episode_key=episode_key,
			episode_state=episode_state,
		)
		if not interaction_name:
			_interaction_fail("CONFIGURATION_ERROR", "The interaction could not be created.")
		stored = frappe.db.get_value(
			"CRM Interaction",
			interaction_name,
			[
				"name",
				"student",
				"crm_contact",
				"channel",
				"direction",
				"interaction_datetime",
				"conversation_id",
				"agent_id",
				"source_revision",
			],
			as_dict=True,
		)
		if not stored or not _external_interaction_matches(stored, target, payload):
			_interaction_fail(
				"IDEMPOTENCY_KEY_REUSED",
				"The external interaction key was already used with another message.",
			)
	for evidence_name in evidence_names:
		frappe.db.set_value(
			"CRM Interaction Evidence", evidence_name, "interaction", interaction_name, update_modified=False
		)
	analysis_run = None
	if payload["evidence_state"] != "draft":
		analysis_run = _ensure_interaction_analysis_run(
			interaction_name, episode_key, payload["source_revision"], evidence_digest
		)
	result = {
		"outcome": "created",
		"interaction": interaction_name,
		"student": target.get("student"),
		"contact": target.get("contact"),
		"analysis_run": analysis_run,
	}
	# Command receipts remain auditable but never copy the raw evidence body.
	receipt_provenance = {
		key: payload.get(key)
		for key in (
			"source_namespace",
			"source_record_id",
			"idempotency_key",
			"student_id",
			"contact_id",
			"target_external_id",
			"channel",
			"direction",
			"occurred_at",
			"agent_id",
			"conversation_id",
			"evidence_kind",
			"evidence_state",
			"source_revision",
		)
	}
	return _persist_receipt(
		keys,
		request_fp=fingerprint,
		result=result,
		principal=authority.get("actor_user") or payload["source_namespace"],
		source_namespace=payload["source_namespace"],
		_source_record_id=payload["source_record_id"],
		idempotency_key=payload["idempotency_key"],
		correlation_id=payload.get("conversation_id") or payload["source_record_id"],
		kind="interaction",
		provenance_payload=receipt_provenance,
	)


def create_interaction(
	*,
	interaction_type,
	student=None,
	crm_contact=None,
	reference_doctype=None,
	reference_docname=None,
	actor=None,
	summary=None,
	notes=None,
	outcome=None,
	interaction_datetime=None,
	channel=None,
	direction=None,
	conversation_id=None,
	agent_id=None,
	source_namespace=None,
	source_record_id=None,
	external_id=None,
	source_revision=None,
	evidence_digest=None,
	evidence=None,
	episode_key=None,
	episode_state=None,
):
	if not student and crm_contact:
		students = students_for_contact(crm_contact)
		# A Contact can belong to multiple historical cases.  Source events that
		# need one Student must provide the Student explicitly; do not silently
		# choose a latest/first case.
		student = students[0] if len(students) == 1 else None

	if not student and not crm_contact:
		return None

	if not frappe.db.exists(
		"CRM Interaction Type", {"name": interaction_type, "enabled": 1}
	):
		frappe.log_error(title=f"Unknown interaction type: {interaction_type}")
		return None

	external_id = (
		external_id
		if external_id is not None
		else external_id_for(reference_doctype, reference_docname, interaction_type)
	)
	if external_id:
		existing = frappe.db.get_value("CRM Interaction", {"external_id": external_id}, "name")
		if existing:
			return existing

	interaction = frappe.new_doc("CRM Interaction")
	interaction.student = student
	interaction.crm_contact = crm_contact
	interaction.interaction_type = interaction_type
	interaction.reference_doctype = reference_doctype
	interaction.reference_docname = reference_docname
	interaction.external_id = external_id
	interaction.actor = actor or frappe.session.user
	interaction.summary = summary or interaction_type
	interaction.notes = notes
	interaction.outcome = outcome
	interaction.interaction_datetime = interaction_datetime or interaction.interaction_datetime
	interaction.channel = channel
	interaction.direction = direction
	interaction.conversation_id = conversation_id
	interaction.agent_id = agent_id
	interaction.source_namespace = source_namespace
	interaction.source_record_id = source_record_id
	interaction.source_revision = source_revision
	interaction.evidence_digest = evidence_digest
	interaction.evidence = evidence
	interaction.episode_key = episode_key
	interaction.episode_state = episode_state
	if student and verify_sla_source(reference_doctype, reference_docname, student):
		interaction.source_verified = 1
	previous_flag = getattr(frappe.flags, "student_sla_source_service", False)
	frappe.flags.student_sla_source_service = True
	savepoint = "create_interaction_external_id_race"
	try:
		try:
			if external_id:
				frappe.db.savepoint(savepoint)
			interaction.insert(ignore_permissions=True)
		except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
			# Two concurrent writers (e.g. a retried webhook delivery and the
			# original request) may both pass the existence check above before
			# either inserts; MariaDB reports that race as a unique-constraint
			# violation on the external_id index. Roll back only the failed
			# insert (not the enclosing request transaction, which may hold the
			# just-inserted source document that triggered this call), re-read,
			# and return the winner's row instead of surfacing a spurious
			# failure to the caller.
			if not external_id:
				raise
			frappe.db.rollback(save_point=savepoint)
			existing = frappe.db.get_value("CRM Interaction", {"external_id": external_id}, "name")
			if not existing:
				raise
			return existing
	finally:
		frappe.flags.student_sla_source_service = previous_flag
	return interaction.name


def satisfy_student_sla_from_interaction(doc, method=None):
	"""Close an eligible Student SLA once a source interaction has an outcome."""
	if not doc.get("student"):
		return None
	if doc.get("outcome") not in {"Captured", "Follow Up Needed", "Resolved", "Converted"}:
		return None
	if doc.get("reference_doctype") not in {"Call Log", "Communication", "Task", "WhatsApp Message"}:
		return None
	if not doc.get("source_verified") or not verify_sla_source(
		doc.reference_doctype, doc.reference_docname, doc.student
	):
		return None
	from crm.fcrm.student_sla import get_student_sla_status, record_qualifying_response

	status = get_student_sla_status(doc.student)
	attempt = status.get("attempt")
	if not attempt:
		return None
	try:
		return record_qualifying_response(attempt["attempt"], doc.name, expected_revision=attempt["revision"])
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
		students = students_for_contact(reference_name)
		student = students[0] if len(students) == 1 else None
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
			doc.reference_doctype, doc.reference_name, "OUTREACH", doc, summary=doc.subject
		)
	except Exception:
		frappe.log_error(title="CRM Interaction creation failed (Communication insert)")


def create_interaction_from_communication_update(doc, method=None):
	# Frappe can invoke on_update during insert.  A Received communication is
	# only a reply when its direction changes on an existing record; treating
	# the initial insert as a reply creates a phantom Connected interaction.
	if doc.is_new() or doc.flags.in_insert:
		return
	if doc.reference_doctype not in ("CRM Contact", "CRM Student"):
		return

	is_reply = doc.sent_or_received == "Received" and doc.has_value_changed("sent_or_received")
	if not is_reply:
		return

	try:
		_create_interaction_for_reference(
			doc.reference_doctype, doc.reference_name, "MESSAGE", doc, summary=doc.subject
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
	# A next-action Task may already be linked to the canonical Interaction
	# that recorded its outcome. Completion must satisfy that event, not
	# create a second timeline row.
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
			"SYSTEM_ACTIVITY",
			doc,
			summary=doc.title,
			actor=doc.assigned_to,
		)
	except Exception:
		frappe.log_error(title="CRM Interaction creation failed (Task update)")


def create_interaction_from_note_insert(doc, method=None):
	"""Record a Sale-authored FCRM Note as a scoped NOTE interaction."""
	if doc.reference_doctype not in ("CRM Contact", "CRM Student"):
		return

	try:
		create_interaction(
			interaction_type="NOTE",
			crm_contact=doc.reference_docname if doc.reference_doctype == "CRM Contact" else None,
			student=doc.reference_docname if doc.reference_doctype == "CRM Student" else None,
			reference_doctype="FCRM Note",
			reference_docname=doc.name,
			actor=doc.owner,
			summary="Ghi chú tư vấn",
			notes=doc.content,
			channel="Internal",
			direction="internal",
			external_id=f"FCRM Note:{doc.name}:NOTE",
		)
	except Exception:
		frappe.log_error(title="CRM Interaction creation failed (FCRM Note insert)")


def create_interaction_from_call_log_insert(doc, method=None):
	if doc.reference_doctype not in ("CRM Contact", "CRM Student"):
		return

	interaction_type = "PHONE_CALL"
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


def create_interaction_for_completed_action(action) -> str | None:
	"""Create the CRM Interaction a completed CRM Action Item represents.

	Only actions with a real contact channel (CALL/EMAIL/MESSAGE) are genuine
	touchpoints; an internal action (default_channel NONE) returns None.
	Caller is responsible for persisting the returned name onto
	``action.linked_interaction`` -- this never writes the Action Item itself.
	"""
	if not action.get("action"):
		return None
	default_channel = frappe.db.get_value("CRM Action", action.action, "default_channel")
	interaction_type = ACTION_CHANNEL_TO_INTERACTION_TYPE.get(default_channel)
	if not interaction_type:
		return None
	try:
		return create_interaction(
			interaction_type=interaction_type,
			student=action.student,
			crm_contact=action.get("contact"),
			reference_doctype="CRM Action Item",
			reference_docname=action.name,
			actor=frappe.session.user,
			summary=action.get("objective") or action.get("action_type") or interaction_type,
			notes=action.get("outcome_notes"),
			outcome=ACTION_OUTCOME_TO_INTERACTION_OUTCOME.get(action.get("outcome_code")),
			channel=default_channel,
			direction="outbound",
		)
	except Exception:
		frappe.log_error(title="CRM Interaction creation failed (Action Item completion)")
		return None


def create_interaction_from_contact_update(doc, method=None):
	# See create_interaction_from_task_update -- on_update fires during insert
	# too, after is_new() has already flipped to False; flags.in_insert is the
	# reliable signal there.
	if doc.is_new() or doc.flags.in_insert:
		return

	if doc.has_value_changed("lifecycle_stage"):
		try:
			create_interaction(
				interaction_type="SYSTEM_ACTIVITY",
				crm_contact=doc.name,
				student=doc.student,
				reference_doctype="CRM Contact",
				reference_docname=doc.name,
				summary=f"Stage changed to {doc.lifecycle_stage}",
			)
		except Exception:
			frappe.log_error(title="CRM Interaction creation failed (Contact stage change)")

	if doc.has_value_changed("owner_staff"):
		interaction_type = "SYSTEM_ACTIVITY"
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
			student=doc.student,
			crm_contact=doc.contact,
			reference_doctype="CRM Contact Consent Event",
			reference_docname=doc.name,
			actor=doc.created_by,
			summary=f"{doc.event_type} ({doc.source or 'system'})",
		)
	except Exception:
		frappe.log_error(title="CRM Interaction creation failed (Consent event)")


def create_interaction_from_marketing_engagement_insert(doc, method=None):
	if frappe.flags.in_patch or getattr(frappe.flags, "student_attribution_service", False):
		return
	try:
		if doc.engagement_kind == "event_participation":
			create_interaction(
				interaction_type="EVENT_PARTICIPATION",
				crm_contact=doc.crm_contact,
				student=doc.student,
				reference_doctype=doc.doctype,
				reference_docname=doc.name,
				actor=doc.actor,
				summary=f"Registered for {doc.crm_event}",
			)
		elif doc.engagement_kind == "campaign_touch":
			create_interaction(
				interaction_type="SYSTEM_ACTIVITY",
				crm_contact=doc.crm_contact,
				student=doc.student,
				reference_doctype=doc.doctype,
				reference_docname=doc.name,
				summary=f"Touched by {doc.crm_campaign}",
			)
	except Exception:
		frappe.log_error(title="CRM Interaction creation failed (Marketing Engagement insert)")


def create_interaction_from_marketing_engagement_update(doc, method=None):
	if frappe.flags.in_patch or getattr(frappe.flags, "student_attribution_service", False):
		return
	if (
		doc.is_new()
		or doc.flags.in_insert
		or doc.engagement_kind != "event_participation"
		or not doc.has_value_changed("status")
	):
		return
	interaction_type = "EVENT_PARTICIPATION"
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
		frappe.log_error(title="CRM Interaction creation failed (Marketing Engagement update)")


def clear_interaction_reference(doc, method=None):
	"""on_trash hook (Communication/Task/Call Log/FCRM Note/CRM Contact Consent Event):
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
