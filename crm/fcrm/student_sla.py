"""Authoritative first-response SLA lifecycle for CRM Student."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from typing import Any

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime as frappe_now_datetime, time_diff_in_seconds

from crm.fcrm.permissions import has_permission as has_student_permission
from crm.fcrm.role_policy import capabilities_for_roles
from crm.fcrm.student_feature_flags import enabled


ATTEMPT_DOCTYPE = "CRM Student SLA Attempt"
EVENT_DOCTYPE = "CRM Student SLA Event"
DELIVERY_DOCTYPE = "CRM Student SLA Delivery"
SERVICE_FLAG = "student_sla_service"
TERMINAL = {"responded", "closed", "closed_inactive", "superseded"}
MEANINGFUL_OUTCOMES = {"Captured", "Follow Up Needed", "Resolved", "Converted"}
LEASE_MINUTES = 5


def _test_seam_active() -> bool:
	"""Allow deterministic time only for the leased disposable Playwright site."""
	run_id = str(frappe.conf.get("crm_playwright_e2e_run_id") or "").strip()
	lease = frappe.cache().get_value("crm_playwright_e2e_lease") or {}
	lease_run_id = str(lease.get("run_id") or "").strip()
	expires_at = get_datetime(lease.get("expires_at")) if lease.get("expires_at") else None
	return (
		getattr(frappe.local, "site", None) == "crm.localhost"
		and frappe.conf.get("crm_playwright_disposable") in (1, "1", True)
		and frappe.conf.get("crm_playwright_test_seam_enabled") in (1, "1", True)
		and bool(run_id)
		and lease_run_id == run_id
		and bool(expires_at and expires_at > frappe_now_datetime())
	)


def now_datetime():
	"""Internal clock seam; production always uses Frappe's wall clock."""
	configured = frappe.conf.get("crm_playwright_test_clock") if _test_seam_active() else None
	return get_datetime(configured) if configured else frappe_now_datetime()


def run_due_sla_worker_for_test(limit: int = 50) -> dict[str, int]:
	"""Non-whitelisted, run-scoped synchronous worker hook for bench tests."""
	if not _test_seam_active():
		_error("TEST_SEAM_DISABLED", "The deterministic SLA worker is disposable-site only.")
	return process_due_sla_attempts(limit=limit)


class StudentSLAError(frappe.ValidationError):
	def __init__(self, code: str, message: str | None = None):
		self.code = code
		self.error_code = code
		super().__init__(message or code)


def _error(code: str, message: str | None = None):
	raise StudentSLAError(code, message)


@contextmanager
def service_context():
	flags = frappe.flags
	previous = getattr(flags, SERVICE_FLAG, False)
	flags.student_sla_service = True
	try:
		yield
	finally:
		flags.student_sla_service = previous


@contextmanager
def delivery_service_context():
	flags = frappe.flags
	previous = getattr(flags, "student_sla_delivery_service", False)
	flags.student_sla_delivery_service = True
	try:
		yield
	finally:
		flags.student_sla_delivery_service = previous


def _policy(campus: str, pool: str | None = None, at=None):
	at = at or now_datetime()
	filters = {"campus": campus, "status": "active", "effective_from": ["<=", at]}
	if pool:
		filters["student_pool"] = pool
	rows = frappe.get_all(
		"CRM Student SLA Policy", filters=filters, fields="*",
		order_by="policy_version desc", limit_page_length=2,
	)
	rows = [row for row in rows if not row.get("effective_until") or row.effective_until > at]
	if len(rows) > 1:
		_error("OVERLAPPING_POLICY", "More than one active SLA policy covers this scope.")
	return rows[0] if rows else None


def _policy_pause_reasons(policy) -> list[str]:
	reasons = policy.get("pause_reasons") or []
	if isinstance(reasons, str):
		try:
			reasons = json.loads(reasons)
		except (TypeError, ValueError):
			return []
	return reasons if isinstance(reasons, list) else []


def _insert_event(attempt, event_type: str, *, actor: str, payload: dict[str, Any] | None = None):
	revision = int(attempt.revision or 0)
	key = f"sla:{attempt.name}:{revision}:{event_type}"
	existing = frappe.db.get_value(EVENT_DOCTYPE, {"idempotency_key": key}, "name")
	if existing:
		return frappe.get_doc(EVENT_DOCTYPE, existing)
	roles = frappe.get_roles(actor) if actor not in {"Administrator", "Guest"} else []
	scope = {"actor_user": actor, "campus_scope": [], "team_scope": [], "student_scope": [attempt.student]}
	values = {
		"doctype": EVENT_DOCTYPE,
		"event_id": str(uuid.uuid4()),
		"event_type": event_type,
		"student": attempt.student,
		"sla_attempt": attempt.name,
		"attempt_revision": revision,
		"ownership_revision": attempt.opening_ownership_revision,
		"sla_policy": attempt.sla_policy,
		"sla_policy_version": attempt.sla_policy_version,
		"actor": actor,
		"scope_snapshot": json.dumps(scope),
		"correlation_token": attempt.correlation_token,
		"idempotency_key": key,
		"payload": json.dumps(payload or {}),
		"event_at": now_datetime(),
		"schema_version": "phase4-v1",
	}
	with service_context():
		doc = frappe.get_doc(values)
		doc.insert(ignore_permissions=True)
	return doc


def _insert_delivery(attempt, event, recipient_role: str, due_at=None):
	"""Legacy delivery projection kept only while the shared-outbox flag is off."""
	key = f"delivery:{event.name}:{recipient_role}"
	existing = frappe.db.get_value(DELIVERY_DOCTYPE, {"idempotency_key": key}, "name")
	if existing:
		return frappe.get_doc(DELIVERY_DOCTYPE, existing)
	with service_context(), delivery_service_context():
		doc = frappe.get_doc(
			{
				"doctype": DELIVERY_DOCTYPE,
				"delivery_key": key,
				"status": "pending",
				"revision": 0,
				"sla_event": event.name,
				"student": attempt.student,
				"channel": "notification",
				"recipient_role": recipient_role,
				"idempotency_key": key,
				"correlation_token": attempt.correlation_token,
				"due_at": due_at or now_datetime(),
				"schema_version": "phase4-v1",
			}
		)
		doc.insert(ignore_permissions=True)
	return doc


def _authorized_recipients(student, recipient_role: str) -> list[str]:
	if recipient_role == "owner":
		user = frappe.db.get_value("CRM Staff", student.owner_staff, "user") if student.owner_staff else None
		candidates = [user] if user else []
	else:
		role = {"lead_sales": "Lead Sales", "admissions_director": "Admissions Director"}.get(recipient_role)
		candidates = frappe.get_all("Has Role", filters={"role": role}, pluck="parent") if role else []
	return [user for user in candidates if user and has_student_permission(student, user=user, permission_type="read")]


def _schedule_delivery(attempt, event, recipient_role: str, due_at=None):
	"""Use one shared infrastructure row per authorized SLA recipient when enabled."""
	if not enabled("shared_sla_outbox"):
		return _insert_delivery(attempt, event, recipient_role, due_at=due_at)
	from crm.api.agent_events import record_sla_notification

	student = frappe.get_doc("CRM Student", attempt.student)
	return [
		record_sla_notification(
			sla_event=event,
			student=student,
			recipient_user=recipient,
			recipient_role=recipient_role,
		)
		for recipient in _authorized_recipients(student, recipient_role)
	]


def open_sla_for_assignment(
	student: str,
	*,
	ownership_event: str,
	ownership_revision: int,
	owner_staff: str,
	owning_team: str,
	student_pool: str | None,
	correlation_token: str,
	actor: str = "Administrator",
	reset_sequence: int = 0,
):
	"""Open or reconcile exactly one attempt after ownership commits."""
	if not enabled("sla"):
		return None
	existing = frappe.get_all(
		ATTEMPT_DOCTYPE,
		filters={"student": student, "status": ["not in", list(TERMINAL)]},
		fields=["name"], limit_page_length=1,
	)
	if existing:
		return frappe.get_doc(ATTEMPT_DOCTYPE, existing[0].name)
	student_doc = frappe.get_doc("CRM Student", student)
	policy = _policy(student_doc.branch, student_pool)
	if not policy:
		_error("NO_ACTIVE_POLICY", "An approved active SLA policy is required before assignment.")
	opened_at = now_datetime()
	warning_at = add_to_date(opened_at, minutes=int(policy.warning_minutes))
	breach_at = add_to_date(opened_at, minutes=int(policy.breach_minutes))
	escalation_at = add_to_date(opened_at, minutes=int(policy.escalation_minutes))
	values = {
		"doctype": ATTEMPT_DOCTYPE,
		"attempt_key": f"sla:{student}:{ownership_revision}:reset:{reset_sequence}",
		"status": "open",
		"revision": 0,
		"reset_sequence": reset_sequence,
		"student": student,
		"opening_ownership_revision": ownership_revision,
		"opening_revision_key": f"{student}:{ownership_revision}:reset:{reset_sequence}",
		"opening_ownership_event": ownership_event,
		"owner_staff": owner_staff,
		"owning_team": owning_team,
		"student_pool": student_pool,
		"campus": student_doc.branch,
		"sla_policy": policy.name,
		"sla_policy_version": policy.policy_version,
		"warning_at": warning_at,
		"breach_at": breach_at,
		"escalation_at": escalation_at,
		"next_transition_at": warning_at,
		"pause_reasons": json.dumps(_policy_pause_reasons(policy)),
		"maximum_pause_minutes": int(policy.maximum_pause_minutes or 0),
		"recipient_strategy": policy.recipient_strategy,
		"opened_at": opened_at,
		"total_paused_minutes": 0,
		"correlation_token": correlation_token,
		"schema_version": "phase4-v1",
	}
	with service_context():
		attempt = frappe.get_doc(values)
		attempt.insert(ignore_permissions=True)
		_insert_event(attempt, "opened", actor=actor, payload={"owner_staff": owner_staff, "owning_team": owning_team, "student_pool": student_pool})
	return attempt


def _lock_attempt(name: str):
	frappe.db.sql(f"select name from `tab{ATTEMPT_DOCTYPE}` where name = %s for update", (name,))
	return frappe.get_doc(ATTEMPT_DOCTYPE, name)


def _assert_scope(attempt):
	student = frappe.get_doc("CRM Student", attempt.student)
	if not has_student_permission(student, user=frappe.session.user, permission_type="read"):
		_error("OUT_OF_SCOPE", "SLA attempt is outside the current Student scope.")
	return student


def pause_sla(attempt_name: str, reason_code: str, *, expected_revision: int):
	if not enabled("sla"):
		_error("SLA_DISABLED", "Student SLA progression is disabled during controlled rollout.")
	actor = frappe.session.user
	attempt = _lock_attempt(attempt_name)
	_assert_scope(attempt)
	if attempt.status != "open":
		_error("INVALID_STATE", "Only an open SLA can be paused.")
	if int(attempt.revision or 0) != int(expected_revision):
		_error("STALE_REVISION", "SLA attempt changed; refresh before retrying.")
	if reason_code not in _policy_pause_reasons(attempt):
		_error("INVALID_PAUSE_REASON", "Pause reason is not approved by the policy snapshot.")
	if int(attempt.maximum_pause_minutes or 0) <= int(attempt.total_paused_minutes or 0):
		_error("PAUSE_LIMIT_REACHED", "The SLA pause allowance has been exhausted.")
	attempt.revision = int(attempt.revision or 0) + 1
	attempt.status = "paused"
	attempt.paused_at = now_datetime()
	attempt.pause_deadline = add_to_date(attempt.paused_at, minutes=int(attempt.maximum_pause_minutes or 0) - int(attempt.total_paused_minutes or 0))
	with service_context():
		attempt.save(ignore_permissions=True)
		_insert_event(attempt, "paused", actor=actor, payload={"reason_code": reason_code})
	frappe.db.commit()
	return _attempt_projection(attempt)


def resume_sla(attempt_name: str, *, expected_revision: int):
	if not enabled("sla"):
		_error("SLA_DISABLED", "Student SLA progression is disabled during controlled rollout.")
	actor = frappe.session.user
	attempt = _lock_attempt(attempt_name)
	_assert_scope(attempt)
	if attempt.status != "paused" or not attempt.paused_at:
		_error("INVALID_STATE", "Only a paused SLA can resume.")
	if int(attempt.revision or 0) != int(expected_revision):
		_error("STALE_REVISION", "SLA attempt changed; refresh before retrying.")
	now = now_datetime()
	if attempt.pause_deadline and now > attempt.pause_deadline:
		_error("PAUSE_EXPIRED", "The approved pause window expired and was reconciled by the SLA worker.")
	paused_minutes = max(0, int(time_diff_in_seconds(now, attempt.paused_at) // 60))
	attempt.total_paused_minutes = int(attempt.total_paused_minutes or 0) + paused_minutes
	attempt.warning_at = add_to_date(attempt.warning_at, minutes=paused_minutes)
	attempt.breach_at = add_to_date(attempt.breach_at, minutes=paused_minutes)
	attempt.escalation_at = add_to_date(attempt.escalation_at, minutes=paused_minutes)
	attempt.next_transition_at = attempt.warning_at
	attempt.paused_at = None
	attempt.status = "open"
	attempt.revision = int(attempt.revision or 0) + 1
	with service_context():
		attempt.save(ignore_permissions=True)
		_insert_event(attempt, "resumed", actor=actor, payload={"pause_minutes": paused_minutes})
	frappe.db.commit()
	return _attempt_projection(attempt)


def record_qualifying_response(attempt_name: str, interaction_name: str, *, expected_revision: int):
	if not enabled("sla"):
		_error("SLA_DISABLED", "Student SLA progression is disabled during controlled rollout.")
	actor = frappe.session.user
	attempt = _lock_attempt(attempt_name)
	_assert_scope(attempt)
	if attempt.status in TERMINAL or attempt.status == "superseded":
		_error("INVALID_STATE", "SLA attempt is already closed.")
	if int(attempt.revision or 0) != int(expected_revision):
		_error("STALE_REVISION", "SLA attempt changed; refresh before retrying.")
	interaction = frappe.get_doc("CRM Interaction", interaction_name)
	frappe.db.sql("select name from `tabCRM Interaction` where name = %s for update", (interaction.name,))
	interaction.reload()
	if interaction.student != attempt.student or interaction.interaction_datetime < attempt.opened_at:
		_error("INVALID_INTERACTION", "Interaction is not a valid response for this Student SLA.")
	if interaction.outcome not in MEANINGFUL_OUTCOMES:
		_error("OUTCOME_REQUIRED", "A qualifying interaction outcome is required.")
	if interaction.actor and interaction.actor != actor and actor != "Administrator":
		_error("UNAUTHORIZED", "Only the authenticated interaction actor may satisfy the SLA.")
	if interaction.reference_doctype not in {"Call Log", "Communication", "Task", "CRM Event Participation", "WhatsApp Message"}:
		_error("INVALID_INTERACTION_SOURCE", "Only an auditable interaction source may satisfy the SLA.")
	from crm.fcrm.interaction_log import verify_sla_source
	if not getattr(interaction, "source_verified", False) or not verify_sla_source(
		interaction.reference_doctype, interaction.reference_docname, attempt.student
	):
		_error("UNVERIFIED_INTERACTION_SOURCE", "The interaction source must be backend-verified for this Student.")
	if getattr(interaction, "sla_response_sealed", False):
		_error("DUPLICATE_RESPONSE", "This interaction has already satisfied an SLA.")
	attempt.response_interaction = interaction.name
	attempt.responded_at = now_datetime()
	attempt.closed_at = attempt.responded_at
	attempt.status = "responded"
	attempt.next_transition_at = None
	attempt.revision = int(attempt.revision or 0) + 1
	with service_context():
		attempt.save(ignore_permissions=True)
		_insert_event(attempt, "responded", actor=actor, payload={"interaction": interaction.name})
		previous_flag = getattr(frappe.flags, "student_sla_response_service", False)
		frappe.flags.student_sla_response_service = True
		try:
			interaction.db_set("sla_response_sealed", 1, update_modified=False)
		finally:
			frappe.flags.student_sla_response_service = previous_flag
	frappe.db.commit()
	return _attempt_projection(attempt)


def request_sla_reset(attempt_name: str, reason: str, evidence_reference: str, *, expected_revision: int):
	if not enabled("sla"):
		_error("SLA_DISABLED", "Student SLA progression is disabled during controlled rollout.")
	actor = frappe.session.user
	attempt = _lock_attempt(attempt_name)
	_assert_scope(attempt)
	if attempt.status in TERMINAL:
		_error("INVALID_STATE", "Only an active SLA can request a reset.")
	if int(attempt.revision or 0) != int(expected_revision):
		_error("STALE_REVISION", "SLA attempt changed; refresh before retrying.")
	if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 2000:
		_error("INVALID_INPUT", "A reset reason is required.")
	if not isinstance(evidence_reference, str) or not evidence_reference.strip():
		_error("INVALID_INPUT", "Linked reset evidence is required.")
	attempt.reset_requested_by = actor
	attempt.reset_requested_at = now_datetime()
	attempt.reset_reason = reason.strip()
	attempt.reset_evidence_reference = evidence_reference.strip()[:255]
	attempt.revision = int(attempt.revision or 0) + 1
	with service_context():
		attempt.save(ignore_permissions=True)
		_insert_event(attempt, "reset_requested", actor=actor, payload={"reason_code": "manual_reset", "evidence_reference": attempt.reset_evidence_reference})
	frappe.db.commit()
	return _attempt_projection(attempt)


def approve_sla_reset(attempt_name: str, *, expected_revision: int):
	if not enabled("sla"):
		_error("SLA_DISABLED", "Student SLA progression is disabled during controlled rollout.")
	actor = frappe.session.user
	attempt = _lock_attempt(attempt_name)
	_assert_scope(attempt)
	if not attempt.reset_requested_by or not attempt.reset_reason or not attempt.reset_evidence_reference:
		_error("RESET_NOT_REQUESTED", "A Lead Sales reset request and evidence are required.")
	if int(attempt.revision or 0) != int(expected_revision):
		_error("STALE_REVISION", "SLA attempt changed; refresh before retrying.")
	reset_sequence = int(attempt.reset_sequence or 0) + 1
	attempt.status = "superseded"
	attempt.reset_approved_by = actor
	attempt.reset_approved_at = now_datetime()
	attempt.next_transition_at = None
	attempt.revision = int(attempt.revision or 0) + 1
	with service_context():
		attempt.save(ignore_permissions=True)
		replacement = open_sla_for_assignment(
			attempt.student,
			ownership_event=attempt.opening_ownership_event,
			ownership_revision=attempt.opening_ownership_revision,
			owner_staff=attempt.owner_staff,
			owning_team=attempt.owning_team,
			student_pool=attempt.student_pool,
			correlation_token=attempt.correlation_token,
			actor=actor,
			reset_sequence=reset_sequence,
		)
		_insert_event(
			attempt,
			"reset_approved",
			actor=actor,
			payload={"prior_attempt": attempt.name, "approver": actor, "replacement_attempt": replacement.name},
		)
	frappe.db.commit()
	return _attempt_projection(replacement)


def get_sla_reset_report(campus: str | None = None) -> dict[str, Any]:
	filters = ""
	values: tuple[Any, ...] = ()
	if campus:
		filters = " and a.campus = %s"
		values = (campus,)
	rows = frappe.db.sql(
		f"""select e.event_type, count(*) as count
		from `tabCRM Student SLA Event` e
		join `tabCRM Student SLA Attempt` a on a.name = e.sla_attempt
		where e.event_type in ('reset_requested', 'reset_approved'){filters}
		group by e.event_type""",
		values,
		as_dict=True,
	)
	return {"campus": campus, "counts": {row.event_type: row.count for row in rows}}


def _attempt_projection(attempt) -> dict[str, Any]:
	return {
		"attempt": attempt.name,
		"student": attempt.student,
		"status": attempt.status,
		"revision": attempt.revision,
		"warning_at": attempt.warning_at,
		"breach_at": attempt.breach_at,
		"escalation_at": attempt.escalation_at,
		"next_transition_at": attempt.next_transition_at,
		"total_paused_minutes": attempt.total_paused_minutes,
		"pause_reasons": _policy_pause_reasons(attempt),
		"maximum_pause_minutes": attempt.maximum_pause_minutes,
		"pause_deadline": attempt.pause_deadline,
		"sla_policy_version": attempt.sla_policy_version,
		"last_event": frappe.db.get_value(EVENT_DOCTYPE, {"sla_attempt": attempt.name}, "name", order_by="event_at desc"),
	}


def get_student_sla_status(student: str) -> dict[str, Any]:
	student_doc = frappe.get_doc("CRM Student", student)
	if not has_student_permission(student_doc, user=frappe.session.user, permission_type="read"):
		_error("OUT_OF_SCOPE", "SLA is outside the current Student scope.")
	attempts = frappe.get_all(ATTEMPT_DOCTYPE, filters={"student": student}, fields=["name"], order_by="creation desc", limit_page_length=1)
	roles = frappe.get_roles(frappe.session.user)
	caps = capabilities_for_roles(roles, administrator=frappe.session.user == "Administrator")
	return {
		"student": student,
		"attempt": _attempt_projection(frappe.get_doc(ATTEMPT_DOCTYPE, attempts[0].name)) if attempts else None,
		"capabilities": {"pause": "student.sla.pause" in caps, "respond": "student.sla.respond" in caps},
	}


def process_due_sla_attempts(limit: int = 50) -> dict[str, int]:
	if not enabled("sla"):
		return {"processed": 0, "failed": 0, "disabled": 1}
	now = now_datetime()
	rows = frappe.get_all(
		ATTEMPT_DOCTYPE,
		filters={
			"status": ["in", ["open", "warned", "breached"]],
			"next_transition_at": ["<=", now],
		},
		pluck="name", order_by="next_transition_at asc", limit_page_length=min(max(int(limit), 1), 100),
	)
	rows.extend(
		row for row in frappe.get_all(
			ATTEMPT_DOCTYPE,
			filters={"status": "paused", "pause_deadline": ["<=", now]},
			pluck="name", order_by="pause_deadline asc", limit_page_length=min(max(int(limit), 1), 100),
		) if row not in rows
	)
	processed = failed = 0
	for name in rows:
		try:
			_process_due_attempt(name, now)
			processed += 1
		except Exception:
			frappe.db.rollback()
			failed += 1
	return {"processed": processed, "failed": failed}


def _process_due_attempt(name: str, now):
	attempt = _lock_attempt(name)
	if attempt.status in TERMINAL:
		return
	if attempt.status == "paused":
		if not attempt.pause_deadline or attempt.pause_deadline > now:
			return
		paused_minutes = max(0, int(time_diff_in_seconds(now, attempt.paused_at) // 60))
		remaining = max(0, int(attempt.maximum_pause_minutes or 0) - int(attempt.total_paused_minutes or 0))
		paused_minutes = min(paused_minutes, remaining)
		attempt.total_paused_minutes = int(attempt.total_paused_minutes or 0) + paused_minutes
		attempt.warning_at = add_to_date(attempt.warning_at, minutes=paused_minutes)
		attempt.breach_at = add_to_date(attempt.breach_at, minutes=paused_minutes)
		attempt.escalation_at = add_to_date(attempt.escalation_at, minutes=paused_minutes)
		attempt.paused_at = None
		attempt.pause_deadline = None
		attempt.status = "open"
		attempt.next_transition_at = attempt.warning_at
		attempt.revision = int(attempt.revision or 0) + 1
		with service_context():
			attempt.save(ignore_permissions=True)
			_insert_event(attempt, "pause_expired", actor="Administrator", payload={"pause_minutes": paused_minutes})
		frappe.db.commit()
		return
	if not attempt.next_transition_at or attempt.next_transition_at > now:
		return
	actor = "Administrator"
	if attempt.status == "open" and now >= attempt.warning_at:
		attempt.status = "warned"
		attempt.next_transition_at = attempt.breach_at
		event_type, recipient = "warned", "owner"
	elif attempt.status in {"open", "warned"} and now >= attempt.breach_at:
		attempt.status = "breached"
		attempt.next_transition_at = attempt.escalation_at
		event_type, recipient = "breached", "lead_sales"
	elif attempt.status == "breached" and now >= attempt.escalation_at:
		attempt.status = "escalated"
		attempt.next_transition_at = None
		event_type, recipient = "escalated", "admissions_director"
	else:
		return
	attempt.revision = int(attempt.revision or 0) + 1
	with service_context():
		attempt.save(ignore_permissions=True)
		payload = {"recipient_role": recipient} if event_type == "escalated" else {"due_at": str(now)}
		event = _insert_event(attempt, event_type, actor=actor, payload=payload)
		# Daily-digest policy keeps the immutable per-lead escalation event but
		# defers Director notification to the scheduled aggregate sender.
		if not (event_type == "escalated" and attempt.recipient_strategy == "owner_warning_lead_breach_director_daily_digest"):
			_schedule_delivery(attempt, event, recipient)
	frappe.db.commit()


def _delivery_recipients(delivery) -> list[str]:
	student = frappe.get_doc("CRM Student", delivery.student)
	return _authorized_recipients(student, delivery.recipient_role)


def _fence_delivery(name: str, *, from_status: str, to_status: str, lease_token: str, revision: int, values: dict[str, Any] | None = None, require_live: bool = True) -> bool:
	"""Compare-and-swap a delivery transition so an expired worker cannot mutate it."""
	values = values or {}
	assignments = ["status = %s", "revision = revision + 1"]
	params: list[Any] = [to_status]
	for fieldname, value in values.items():
		assignments.append(f"{fieldname} = %s")
		params.append(value)
	where = "name = %s and status = %s and lease_token = %s and revision = %s"
	params.extend([name, from_status, lease_token, revision])
	if require_live:
		where += " and lease_expires_at > %s"
		params.append(now_datetime())
	result = frappe.db.sql(
		f"""update `tab{DELIVERY_DOCTYPE}`
		set {', '.join(assignments)}
		where {where}""",
		params,
	)
	return bool(getattr(result, "rowcount", 0) or frappe.db.sql("select row_count()", as_dict=False)[0][0])


def process_pending_sla_deliveries(limit: int = 50) -> dict[str, int]:
	"""Bounded, leased notification outbox with per-recipient reauthorization."""
	# Shared-outbox cutover stops new legacy writes, not delivery of pre-cutover
	# rows. Drain those rows even if the legacy writer flag is already off.
	if not enabled("delivery") and not enabled("shared_sla_outbox"):
		return {"processed": 0, "failed": 0, "disabled": 1}
	now = now_datetime()
	rows = frappe.get_all(
		DELIVERY_DOCTYPE,
		filters={"status": "pending", "due_at": ["<=", now]},
		pluck="name", order_by="due_at asc", limit_page_length=min(max(int(limit), 1), 100),
	)
	rows.extend(
		row for row in frappe.get_all(
			DELIVERY_DOCTYPE,
			filters={"status": ["in", ["leased", "delivering"]], "lease_expires_at": ["<", now]},
			pluck="name", order_by="lease_expires_at asc", limit_page_length=min(max(int(limit), 1), 100),
		) if row not in rows
	)
	processed = failed = 0
	for name in rows:
		try:
			frappe.db.sql(f"select name from `tab{DELIVERY_DOCTYPE}` where name = %s for update", (name,))
			delivery = frappe.get_doc(DELIVERY_DOCTYPE, name)
			if delivery.status in {"leased", "delivering"}:
				if delivery.lease_expires_at and delivery.lease_expires_at > now:
					continue
				delivery.status = "pending"
				delivery.lease_token = None
				delivery.lease_expires_at = None
				delivery.revision = int(delivery.revision or 0) + 1
				with delivery_service_context():
					delivery.save(ignore_permissions=True)
				frappe.db.commit()
			if delivery.status != "pending":
				continue
			delivery.lease_token = str(uuid.uuid4())
			delivery.lease_expires_at = add_to_date(now, minutes=LEASE_MINUTES)
			delivery.status = "leased"
			delivery.attempt_count = int(delivery.attempt_count or 0) + 1
			delivery.revision = int(delivery.revision or 0) + 1
			with delivery_service_context():
				delivery.save(ignore_permissions=True)
			frappe.db.commit()  # durable claim before provider side effect
			claim_revision = int(delivery.revision or 0)
			lease_token = delivery.lease_token
			if not _fence_delivery(
				name,
				from_status="leased",
				to_status="delivering",
				lease_token=lease_token,
				revision=claim_revision,
				values={"lease_expires_at": add_to_date(now_datetime(), minutes=LEASE_MINUTES)},
			):
				frappe.db.rollback()
				continue
			frappe.db.commit()

			delivery = frappe.get_doc(DELIVERY_DOCTYPE, name)

			recipients = _delivery_recipients(delivery)
			if not recipients:
				if _fence_delivery(
					name,
					from_status="delivering",
					to_status="failed",
					lease_token=lease_token,
					revision=claim_revision + 1,
					values={"last_error_code": "NO_AUTHORIZED_RECIPIENT"},
				):
					frappe.db.commit()
				else:
					frappe.db.rollback()
				failed += 1
				continue
			published = True
			for recipient in recipients:
				# Reserve each recipient independently before the provider side effect.
				# A reclaimed worker sees the same key and never publishes twice.
				# The logical delivery/recipient pair is the idempotency boundary;
				# retries must reuse it even when the lease attempt count changes.
				submission_key = f"{delivery.name}:{recipient}"
				attempt_outcome = frappe.db.get_value(
					"CRM Student SLA Delivery Attempt",
					{"provider_submission_key": submission_key},
					"outcome",
				)
				if attempt_outcome == "delivered":
					continue
				if not attempt_outcome:
					if not frappe.db.sql(
						f"select 1 from `tab{DELIVERY_DOCTYPE}` where name = %s and status = 'delivering' and lease_token = %s and revision = %s and lease_expires_at > %s",
						(name, lease_token, claim_revision + 1, now_datetime()),
					):
						published = False
						break
					with delivery_service_context():
						frappe.get_doc({
							"doctype": "CRM Student SLA Delivery Attempt",
							"delivery_attempt_key": submission_key,
							"delivery": delivery.name,
							"recipient": recipient,
							"attempt_number": delivery.attempt_count,
							"provider_submission_key": submission_key,
							"outcome": "submitted",
							"submitted_at": now_datetime(),
							"schema_version": "phase4-v1",
						}).insert(ignore_permissions=True)
					frappe.db.commit()
				# A submitted-but-not-completed reservation is retried with the
				# same provider key until the provider call returns successfully.
				if not frappe.db.sql(
					f"select 1 from `tab{DELIVERY_DOCTYPE}` where name = %s and status = 'delivering' and lease_token = %s and revision = %s and lease_expires_at > %s",
					(name, lease_token, claim_revision + 1, now_datetime()),
				):
					published = False
					break
				frappe.publish_realtime(
					"student_sla_alert",
					{"status": delivery.recipient_role, "delivery": delivery.name, "submission_key": submission_key},
					user=recipient,
				)
				if not frappe.db.sql(
					f"select 1 from `tab{DELIVERY_DOCTYPE}` where name = %s and status = 'delivering' and lease_token = %s and revision = %s and lease_expires_at > %s",
					(name, lease_token, claim_revision + 1, now_datetime()),
				):
					published = False
					break
				with delivery_service_context():
					attempt_name = frappe.db.get_value(
						"CRM Student SLA Delivery Attempt",
						{"provider_submission_key": submission_key},
						"name",
					)
					attempt_doc = frappe.get_doc("CRM Student SLA Delivery Attempt", attempt_name)
					attempt_doc.outcome = "delivered"
					attempt_doc.completed_at = now_datetime()
					attempt_doc.save(ignore_permissions=True)
				frappe.db.commit()
			finalized = published and _fence_delivery(
				name,
				from_status="delivering",
				to_status="delivered",
				lease_token=lease_token,
				revision=claim_revision + 1,
				values={"delivered_at": now_datetime(), "lease_expires_at": None},
			)
			if not finalized:
				frappe.db.rollback()
				failed += 1
				continue
			delivery = frappe.get_doc(DELIVERY_DOCTYPE, name)
			frappe.db.commit()
			processed += 1
		except Exception:
			frappe.db.rollback()
			failed += 1
	return {"processed": processed, "failed": failed}
