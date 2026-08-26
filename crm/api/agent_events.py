"""Transactional outbox for crm-agents notifications.

The CRM record mutation and its event are committed by the same MariaDB
transaction. Delivery is asynchronous and retryable; crm-agents treats the
event as a signal and re-reads the authoritative CRM row.
"""
import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta

import frappe
import requests
from frappe.utils import now_datetime

from crm.fcrm.permissions import has_permission as has_student_permission
from crm.fcrm.record_retention import technical_retention_until


_EVENT_PATHS = {
	"recommendation.decided.v1": "/api/v1/insight/recommendation-decision",
	"sales_action.outcome_recorded.v1": "/api/v1/insight/sales-action-outcome",
	"student.context_changed.v2": "/api/v1/insight/student-context-v2",
	"student.score_input_changed.v1": "/api/v1/insight/score-input-v1",
	"scoring.policy_changed.v1": "/api/v1/insight/scoring-policy-changed",
}
_MAX_DELIVERY_ATTEMPTS = 10
_LEASE_SECONDS = 120
SLA_NOTIFICATION_EVENT = "student.sla.notification.v1"
SLA_DIGEST_EVENT = "student.sla.digest.v1"
_SLA_OUTBOX_FIELDS = {"source_doctype", "source_event", "delivery_key", "channel", "recipient_user", "recipient_role", "payload", "correlation_token", "retention_until", "legal_hold"}


def _event_fields() -> set[str]:
	try:
		return {field.fieldname for field in frappe.get_meta("CRM Agent Event").fields}
	except Exception:
		return set()


def quiesce_agent_events(aggregate_names: list[str]) -> dict:
	"""Stop retryable fixture deliveries before distributed state is removed."""
	if not aggregate_names:
		return {"quiesced": 0, "processing": 0}
	frappe.db.sql(
		"""UPDATE `tabCRM Agent Event`
		SET status = 'quiesced'
		WHERE aggregate_name IN %(aggregate_names)s AND status = 'pending'""",
		{"aggregate_names": aggregate_names},
	)
	processing = frappe.db.count(
		"CRM Agent Event", {"aggregate_name": ["in", aggregate_names], "status": "processing"}
	)
	if processing:
		frappe.throw(
			f"Cannot reset fixture while {processing} crm-agents event(s) are processing.",
			frappe.ValidationError,
		)
	return {
		"quiesced": frappe.db.count(
			"CRM Agent Event", {"aggregate_name": ["in", aggregate_names], "status": "quiesced"}
		),
		"processing": 0,
	}


def _retention_until():
	return technical_retention_until("outbox")


def _enqueue_delivery(event) -> None:
	frappe.enqueue(
		"crm.api.agent_events.deliver_agent_event",
		queue="short",
		enqueue_after_commit=True,
		event_name=event.name,
	)


def record_agent_event(event_type: str, doc) -> str:
	"""Persist an agent-webhook event in the caller's current transaction."""
	if frappe.conf.get("crm_agents_outbox_enabled", 1) in (0, "0", False):
		return ""
	if event_type not in _EVENT_PATHS:
		frappe.throw(f"Unsupported crm-agents event type: {event_type}")
	event_id = str(uuid.uuid4())
	values = {
		"doctype": "CRM Agent Event",
		"event_id": event_id,
		"event_type": event_type,
		"aggregate_doctype": doc.doctype,
		"aggregate_name": doc.name,
		"source_revision": str(doc.modified or now_datetime()),
		"contract_version": 1,
		"occurred_at": now_datetime(),
		"status": "pending",
		"next_attempt_at": now_datetime(),
	}
	fields = _event_fields()
	if "delivery_key" in fields:
		values["delivery_key"] = f"agent:{event_id}"
	if "retention_until" in fields:
		values["retention_until"] = _retention_until()
	event = frappe.get_doc(values)
	event.insert(ignore_permissions=True)
	_enqueue_delivery(event)
	return event.name


def record_student_context_event(student: str, revision: int, *, event_id: str | None = None) -> str:
	"""Coalesce only an undispatched v2 Student event; never rewrite a claim."""
	rollout_epoch = int(frappe.conf.get("crm_agents_v2_rollout_epoch", 0) or 0)
	pending = frappe.db.sql(
		"SELECT name FROM `tabCRM Agent Event` WHERE aggregate_doctype = %s AND aggregate_name = %s "
		"AND event_type = %s AND status = 'pending' ORDER BY creation DESC LIMIT 1 FOR UPDATE",
		("CRM Student", student, "student.context_changed.v2"),
		as_dict=True,
	)
	if pending:
		event_name = pending[0].name
		frappe.db.sql(
			"UPDATE `tabCRM Agent Event` SET source_revision = %s, source_revision_bigint = %s, "
			"occurred_at = %s, rollout_epoch = %s WHERE name = %s AND status = 'pending'",
			(str(revision), revision, now_datetime(), rollout_epoch, event_name),
		)
	else:
		event = frappe.get_doc(
			{
				"doctype": "CRM Agent Event",
				"event_id": event_id or str(uuid.uuid4()),
				"event_type": "student.context_changed.v2",
				"aggregate_doctype": "CRM Student",
				"aggregate_name": student,
				"source_revision": str(revision),
				"source_revision_bigint": revision,
				"contract_version": 2,
				"rollout_epoch": rollout_epoch,
				"occurred_at": now_datetime(),
				"status": "pending",
				"next_attempt_at": now_datetime(),
			}
		).insert(ignore_permissions=True)
		event_name = event.name
	_enqueue_delivery(frappe.get_doc("CRM Agent Event", event_name))
	return event_name


def record_score_input_event(student: str, revision: int, *, event_id: str | None = None) -> str:
	"""Coalesce only an undispatched scoring event; never rewrite a claim.

	Uses the same shared `CRM Agent Event` outbox as `record_student_context_event`
	but its own `event_type`/`source_revision_bigint` lineage, so a burst of
	Interaction/Intent/Student writes for one student collapses into a single
	pending scoring event exactly like student-context-v2 does for its own
	stream -- the two streams never coalesce into each other because the
	`event_type` filter partitions them into an independent scoring
	namespace.
	"""
	if frappe.conf.get("crm_agents_scoring_events_enabled", 0) in (0, "0", False):
		return ""
	pending = frappe.db.sql(
		"SELECT name FROM `tabCRM Agent Event` WHERE aggregate_doctype = %s AND aggregate_name = %s "
		"AND event_type = %s AND status = 'pending' ORDER BY creation DESC LIMIT 1 FOR UPDATE",
		("CRM Student", student, "student.score_input_changed.v1"),
		as_dict=True,
	)
	if pending:
		event_name = pending[0].name
		frappe.db.sql(
			"UPDATE `tabCRM Agent Event` SET source_revision = %s, source_revision_bigint = %s, "
			"occurred_at = %s WHERE name = %s AND status = 'pending'",
			(str(revision), revision, now_datetime(), event_name),
		)
	else:
		event = frappe.get_doc(
			{
				"doctype": "CRM Agent Event",
				"event_id": event_id or str(uuid.uuid4()),
				"event_type": "student.score_input_changed.v1",
				"aggregate_doctype": "CRM Student",
				"aggregate_name": student,
				"source_revision": str(revision),
				"source_revision_bigint": revision,
				"contract_version": 1,
				"occurred_at": now_datetime(),
				"status": "pending",
				"next_attempt_at": now_datetime(),
			}
		).insert(ignore_permissions=True)
		event_name = event.name
	_enqueue_delivery(frappe.get_doc("CRM Agent Event", event_name))
	return event_name


def record_sla_notification(*, sla_event, student, recipient_user: str, recipient_role: str) -> str:
	"""Write one PII-minimized, per-recipient SLA notification to the shared outbox."""
	fields = _event_fields()
	if not _SLA_OUTBOX_FIELDS.issubset(fields):
		frappe.throw("CRM Agent Event shared-outbox fields are not migrated.")
	key = f"sla:{sla_event.name}:{recipient_user}:realtime"
	existing = frappe.db.get_value("CRM Agent Event", {"delivery_key": key}, "name")
	if existing:
		return existing
	payload = {"student": student.name, "sla_event": sla_event.name, "event_type": sla_event.event_type, "correlation_token": sla_event.correlation_token}
	event = frappe.get_doc(
		{
			"doctype": "CRM Agent Event",
			"event_id": str(uuid.uuid4()),
			"event_type": SLA_NOTIFICATION_EVENT,
			"aggregate_doctype": "CRM Student",
			"aggregate_name": student.name,
			"source_revision": str(sla_event.attempt_revision),
			"contract_version": 1,
			"source_doctype": "CRM Student SLA Event",
			"source_event": sla_event.name,
			"delivery_key": key,
			"channel": "realtime",
			"recipient_user": recipient_user,
			"recipient_role": recipient_role,
			"payload": json.dumps(payload, sort_keys=True, separators=(",", ":")),
			"correlation_token": sla_event.correlation_token,
			"occurred_at": now_datetime(),
			"status": "pending",
			"next_attempt_at": now_datetime(),
			"retention_until": _retention_until(),
		}
	)
	event.insert(ignore_permissions=True)
	_enqueue_delivery(event)
	return event.name


def record_sla_digest(*, recipient_user: str, digest_date: str, unresolved_count: int) -> str:
	"""Write one PII-free daily Student SLA digest per Director."""
	fields = _event_fields()
	if not _SLA_OUTBOX_FIELDS.issubset(fields):
		frappe.throw("CRM Agent Event shared-outbox fields are not migrated.")
	key = f"sla-digest:{recipient_user}:{digest_date}"
	existing = frappe.db.get_value("CRM Agent Event", {"delivery_key": key}, "name")
	if existing:
		return existing
	payload = {"digest_date": digest_date, "unresolved_count": int(unresolved_count), "worklist_url": "/app/student-worklist"}
	event = frappe.get_doc(
		{
			"doctype": "CRM Agent Event",
			"event_id": str(uuid.uuid4()),
			"event_type": SLA_DIGEST_EVENT,
			"aggregate_doctype": "CRM Student SLA Digest",
			"aggregate_name": key,
			"source_revision": digest_date,
			"contract_version": 1,
			"delivery_key": key,
			"channel": "realtime",
			"recipient_user": recipient_user,
			"recipient_role": "Admissions Director",
			"payload": json.dumps(payload, sort_keys=True, separators=(",", ":")),
			"occurred_at": now_datetime(),
			"status": "pending",
			"next_attempt_at": now_datetime(),
			"retention_until": _retention_until(),
		}
	)
	try:
		event.insert(ignore_permissions=True)
	except Exception as exc:
		# The delivery key is unique; a concurrent scheduler run may win the
		# insert between our read and write. Reuse its event instead of failing
		# the remaining Directors.
		if "duplicate" not in str(exc).casefold() and "unique" not in str(exc).casefold():
			raise
		existing = frappe.db.get_value("CRM Agent Event", {"delivery_key": key}, "name")
		if not existing:
			raise
		return existing
	_enqueue_delivery(event)
	return event.name


def send_daily_sla_director_digests() -> dict[str, int]:
	"""Create one aggregate notification for each Director with unresolved escalations."""
	from frappe.utils import add_days, getdate

	digest_date = str(add_days(getdate(now_datetime()), -1))
	window_start = f"{digest_date} 00:00:00"
	window_end = f"{digest_date} 23:59:59"
	count = frappe.db.count(
		"CRM Student SLA Attempt",
		{
			"status": "escalated",
			"recipient_strategy": "owner_warning_lead_breach_director_daily_digest",
			"escalation_at": ["between", [window_start, window_end]],
		},
	)
	if not count:
		return {"created": 0, "skipped": 0}
	directors = frappe.get_all("Has Role", filters={"role": "Admissions Director", "parenttype": "User"}, pluck="parent")
	directors = [
		user
		for user in sorted(set(directors))
		if frappe.db.get_value("User", user, "enabled")
	]
	created = 0
	for director in sorted(set(directors)):
		key = f"sla-digest:{director}:{digest_date}"
		existing = frappe.db.get_value("CRM Agent Event", {"delivery_key": key}, "name")
		record_sla_digest(recipient_user=director, digest_date=digest_date, unresolved_count=count)
		if not existing:
			created += 1
	return {"created": created, "skipped": 0}


def _event_body(event) -> bytes:
	payload = {
			"event_id": event.event_id,
			"event_type": event.event_type,
			"aggregate_doctype": event.aggregate_doctype,
			"aggregate_name": event.aggregate_name,
			"source_revision": event.source_revision,
			"contract_version": event.contract_version,
			"occurred_at": str(event.occurred_at),
		}
	if event.event_type == "student.context_changed.v2":
		payload.update(
			{
				"source_revision": int(event.source_revision_bigint or event.source_revision),
				"contract_version": 2,
				"rollout_epoch": int(event.rollout_epoch or 0),
			}
		)
	elif event.event_type == "student.score_input_changed.v1":
		payload.update(
			{
				"source_revision": int(event.source_revision_bigint or event.source_revision),
				"contract_version": 1,
			}
		)
	return json.dumps(
		payload,
		sort_keys=True,
		separators=(",", ":"),
	).encode()


def _complete_delivery(event, lease_id: str, *, status: str = "delivered", error: str | None = None) -> None:
	fields = _event_fields()
	where = "name = %(name)s" + (" and lease_id = %(lease_id)s" if "lease_id" in fields else "")
	values = {"name": event.name, "lease_id": lease_id, "at": now_datetime(), "error": error}
	frappe.db.sql(
		"update `tabCRM Agent Event` set status = %(status)s, delivered_at = %(at)s, last_error = %(error)s where " + where,
		{**values, "status": status},
	)


def _deliver_realtime_notification(event, lease_id: str) -> bool:
	"""Publish an SLA alert only if the recipient remains in Student scope."""
	try:
		if not event.recipient_user or not event.aggregate_name:
			raise ValueError("Invalid shared SLA outbox contract")
		payload = json.loads(event.payload or "{}")
		if event.event_type == SLA_DIGEST_EVENT:
			if (
				event.recipient_role != "Admissions Director"
				or not frappe.db.get_value("User", event.recipient_user, "enabled")
				or not frappe.db.exists("Has Role", {"parent": event.recipient_user, "role": "Admissions Director"})
			):
				_complete_delivery(event, lease_id, status="cancelled", error="RECIPIENT_ROLE_REVOKED")
				return True
			if not isinstance(payload, dict) or set(payload) - {"digest_date", "unresolved_count", "worklist_url"}:
				raise ValueError("Shared SLA digest payload contains unsupported fields")
			frappe.publish_realtime("student_sla_digest", payload, user=event.recipient_user)
		else:
			if event.aggregate_doctype != "CRM Student":
				raise ValueError("Invalid shared SLA aggregate")
			student = frappe.get_doc("CRM Student", event.aggregate_name)
			if not has_student_permission(student, user=event.recipient_user, permission_type="read"):
				_complete_delivery(event, lease_id, status="cancelled", error="RECIPIENT_OUT_OF_SCOPE")
				return True
			if not isinstance(payload, dict) or set(payload) - {"student", "sla_event", "event_type", "correlation_token"}:
				raise ValueError("Shared SLA payload contains unsupported fields")
			frappe.publish_realtime("student_sla_alert", payload, user=event.recipient_user)
	except Exception as exc:
		_record_delivery_failure(event, str(exc), lease_id)
		return False
	_complete_delivery(event, lease_id)
	return True


def deliver_agent_event(event_name: str) -> None:
	"""Deliver one event under a fenced lease (legacy schemas fail closed)."""
	event = frappe.get_doc("CRM Agent Event", event_name)
	fields = _event_fields()
	if not {"lease_id", "lease_expires_at"}.issubset(fields):
		# Do not claim a fenced-lease event with the old non-fenced protocol.
		if str(event.event_type).startswith(("recommendation.", "sales_action.")):
			frappe.throw("CRM Agent Event lease fields are required for fenced delivery.")
	if event.status not in {"pending", "processing"}:
		return
	lease_id = str(uuid.uuid4())
	lease_until = now_datetime() + timedelta(seconds=_LEASE_SECONDS)
	claim_condition = "(status = 'pending' or (status = 'processing' and lease_expires_at < %(now)s))" if {"lease_id", "lease_expires_at"}.issubset(fields) else "status = 'pending'"
	frappe.db.sql(
		"UPDATE `tabCRM Agent Event` SET status = 'processing'" + (", lease_id = %(lease_id)s, lease_expires_at = %(lease_until)s" if {"lease_id", "lease_expires_at"}.issubset(fields) else "") + " WHERE name = %(name)s AND " + claim_condition,
		{"name": event.name, "lease_id": lease_id, "lease_until": lease_until, "now": now_datetime()},
	)
	if frappe.db.sql("SELECT ROW_COUNT() AS affected", as_dict=True)[0].affected != 1:
		return
	event.reload()
	if (event.get("channel") or "agent_webhook") == "realtime":
		_deliver_realtime_notification(event, lease_id)
		return
	base_url = frappe.conf.get("crm_agents_url")
	secret = frappe.conf.get("crm_agents_webhook_secret")
	kid = frappe.conf.get("crm_agents_webhook_kid", "v1")
	if not base_url or not secret:
		_record_delivery_failure(event, "crm_agents_url / crm_agents_webhook_secret not configured", lease_id)
		return
	body = _event_body(event)
	timestamp = str(int(time.time()))
	signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
	try:
		response = requests.post(
			f"{base_url.rstrip('/')}{_EVENT_PATHS[event.event_type]}",
			data=body,
			headers={
				"Content-Type": "application/json",
				"X-CRM-Signature": f"sha256={signature}",
				"X-CRM-Timestamp": timestamp,
				"X-CRM-KID": kid,
			},
			timeout=10,
		)
		response.raise_for_status()
	except Exception as exc:
		_record_delivery_failure(event, str(exc), lease_id)
		frappe.log_error(title="crm-agents outbox delivery failed", message=f"event={event.name}: {exc}")
		return
	_complete_delivery(event, lease_id)


def _record_delivery_failure(event, error: str, lease_id: str | None = None) -> None:
	"""Persist bounded exponential backoff and terminal dead-letter status."""
	fields = _event_fields()
	where = "name = %(name)s"
	values = {"name": event.name, "error": error[:500]}
	if lease_id and "lease_id" in fields:
		where += " AND lease_id = %(lease_id)s"
		values["lease_id"] = lease_id
	# Fence every failure write on the lease. A worker whose lease was reclaimed
	# cannot reset the newer worker's delivered/pending state.
	frappe.db.sql(f"UPDATE `tabCRM Agent Event` SET attempts = attempts + 1, last_error = %(error)s WHERE {where}", values)
	updated = frappe.db.sql("SELECT attempts FROM `tabCRM Agent Event` WHERE name = %(name)s" + (" AND lease_id = %(lease_id)s" if lease_id and "lease_id" in fields else ""), values, as_dict=True)
	if not updated:
		return
	attempts = int(updated[0].attempts or 0)
	if attempts >= _MAX_DELIVERY_ATTEMPTS:
		frappe.db.sql(f"UPDATE `tabCRM Agent Event` SET status = 'dead_letter' WHERE {where}", values)
		return
	# Bound retries so one unavailable consumer cannot make the oldest events
	# monopolise every scheduled replay pass.
	delay_minutes = min(60 * (2 ** min(attempts - 1, 5)), 24 * 60)
	values["next_attempt_at"] = now_datetime() + timedelta(minutes=delay_minutes)
	frappe.db.sql(f"UPDATE `tabCRM Agent Event` SET status = 'pending', next_attempt_at = %(next_attempt_at)s WHERE {where}", values)


def retry_pending_agent_events() -> None:
	"""Bounded replay for transient failures; no event is deleted automatically."""
	fields = _event_fields()
	filters = [["next_attempt_at", "<=", now_datetime()]]
	if {"lease_id", "lease_expires_at"}.issubset(fields):
		filters = [["status", "in", ["pending", "processing"]], ["next_attempt_at", "<=", now_datetime()]]
	else:
		filters = [["status", "=", "pending"], ["next_attempt_at", "<=", now_datetime()]]
	for name in frappe.get_all(
		"CRM Agent Event",
		filters=filters,
		order_by="next_attempt_at asc, creation asc",
		pluck="name",
		limit_page_length=100,
	):
		try:
			deliver_agent_event(name)
		except Exception as exc:
			frappe.db.rollback()
			frappe.log_error(title="crm-agents outbox replay failed", message=f"event={name}: {exc}")


def reconcile_student_context_v2(limit: int = 500) -> dict:
	"""Replay the immutable global sequence with a durable cursor."""
	if frappe.conf.get("crm_agents_v2_reconciliation_enabled", 0) in (0, "0", False):
		return {"discovered": 0, "enabled": False}
	cache_key = "crm_agents_v2:context-change-cursor"
	last = int(frappe.cache().get_value(cache_key) or 0)
	rows = frappe.get_all(
		"CRM Student Context Change",
		filters=[["global_sequence", ">", last]],
		fields=["name", "student", "revision", "global_sequence", "event_id"],
		order_by="global_sequence asc",
		limit_page_length=min(int(limit), 1000),
	)
	for row in rows:
		record_student_context_event(row.student, int(row.revision), event_id=row.event_id)
	if rows:
		frappe.cache().set_value(cache_key, int(rows[-1].global_sequence))
	return {"discovered": len(rows), "oldest_unchecked": rows[0].global_sequence if rows else None}


def reconcile_score_input_v1(limit: int = 500) -> dict:
	"""Replay `CRM Score Input Change`'s immutable global sequence with a
	durable cursor -- recovers a missed scoring event without reprocessing a
	revision the consumer's inbox high-water already settled."""
	if frappe.conf.get("crm_agents_scoring_reconciliation_enabled", 0) in (0, "0", False):
		return {"discovered": 0, "enabled": False}
	cache_key = "crm_agents_scoring:score-input-cursor"
	last = int(frappe.cache().get_value(cache_key) or 0)
	rows = frappe.get_all(
		"CRM Score Input Change",
		filters=[["global_sequence", ">", last]],
		fields=["name", "student", "revision", "global_sequence", "event_id"],
		order_by="global_sequence asc",
		limit_page_length=min(int(limit), 1000),
	)
	for row in rows:
		record_score_input_event(row.student, int(row.revision), event_id=row.event_id)
	if rows:
		frappe.cache().set_value(cache_key, int(rows[-1].global_sequence))
	return {"discovered": len(rows), "oldest_unchecked": rows[0].global_sequence if rows else None}
