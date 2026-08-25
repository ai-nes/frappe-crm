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

_EVENT_PATHS = {
	"recommendation.decided.v1": "/api/v1/insight/recommendation-decision",
	"sales_action.outcome_recorded.v1": "/api/v1/insight/sales-action-outcome",
	"student.context_changed.v2": "/api/v1/insight/student-context-v2",
}
_MAX_DELIVERY_ATTEMPTS = 10


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


def record_agent_event(event_type: str, doc) -> str:
	"""Persist an event in the caller's current transaction and schedule delivery."""
	if frappe.conf.get("crm_agents_outbox_enabled", 1) in (0, "0", False):
		return ""
	if event_type not in _EVENT_PATHS:
		frappe.throw(f"Unsupported crm-agents event type: {event_type}")
	event = frappe.get_doc(
		{
			"doctype": "CRM Agent Event",
			"event_id": str(uuid.uuid4()),
			"event_type": event_type,
			"aggregate_doctype": doc.doctype,
			"aggregate_name": doc.name,
			"source_revision": str(doc.modified or now_datetime()),
			"contract_version": 1,
			"occurred_at": now_datetime(),
			"status": "pending",
			"next_attempt_at": now_datetime(),
		}
	)
	event.insert(ignore_permissions=True)
	frappe.enqueue(
		"crm.api.agent_events.deliver_agent_event",
		queue="short",
		enqueue_after_commit=True,
		event_name=event.name,
	)
	return event.name


def record_student_context_event(student: str, revision: int, *, event_id: str | None = None) -> str:
	"""Coalesce only an undispatched v2 Student event; never rewrite a claim."""
	if frappe.conf.get("crm_agents_v2_enabled", 0) in (0, "0", False):
		return ""
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
	frappe.enqueue(
		"crm.api.agent_events.deliver_agent_event",
		queue="short",
		enqueue_after_commit=True,
		event_name=event_name,
	)
	return event_name


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
	return json.dumps(
		payload,
		sort_keys=True,
		separators=(",", ":"),
	).encode()


def deliver_agent_event(event_name: str) -> None:
	"""Deliver one pending event. Failures stay pending for scheduled replay."""
	event = frappe.get_doc("CRM Agent Event", event_name)
	if event.status != "pending":
		return
	frappe.db.sql(
		"UPDATE `tabCRM Agent Event` SET status = 'processing' WHERE name = %s AND status = 'pending'",
		(event.name,),
	)
	if frappe.db.sql("SELECT ROW_COUNT() AS affected", as_dict=True)[0].affected != 1:
		return
	event.reload()
	base_url = frappe.conf.get("crm_agents_url")
	secret = frappe.conf.get("crm_agents_webhook_secret")
	kid = frappe.conf.get("crm_agents_webhook_kid", "v1")
	if not base_url or not secret:
		_record_delivery_failure(event, "crm_agents_url / crm_agents_webhook_secret not configured")
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
		_record_delivery_failure(event, str(exc))
		frappe.log_error(title="crm-agents outbox delivery failed", message=f"event={event.name}: {exc}")
		return
	event.db_set("status", "delivered")
	event.db_set("delivered_at", now_datetime())
	event.db_set("last_error", None)


def _record_delivery_failure(event, error: str) -> None:
	"""Persist bounded exponential backoff and terminal dead-letter status."""
	attempts = (event.attempts or 0) + 1
	event.db_set("attempts", attempts)
	event.db_set("last_error", error[:500])
	if attempts >= _MAX_DELIVERY_ATTEMPTS:
		event.db_set("status", "dead_letter")
		return
	event.db_set("status", "pending")
	# Bound retries so one unavailable consumer cannot make the oldest events
	# monopolise every scheduled replay pass.
	delay_minutes = min(60 * (2 ** min(attempts - 1, 5)), 24 * 60)
	event.db_set("next_attempt_at", now_datetime() + timedelta(minutes=delay_minutes))


def retry_pending_agent_events() -> None:
	"""Bounded replay for transient failures; no event is deleted automatically."""
	for name in frappe.get_all(
		"CRM Agent Event",
		filters=[["status", "=", "pending"], ["next_attempt_at", "<=", now_datetime()]],
		order_by="next_attempt_at asc, creation asc",
		pluck="name",
		limit_page_length=100,
	):
		deliver_agent_event(name)


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
	frappe.cache().set_value(cache_key, int(row.global_sequence))
	return {"discovered": len(rows), "oldest_unchecked": rows[0].global_sequence if rows else None}
