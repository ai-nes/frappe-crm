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
from frappe.utils import get_datetime
from frappe.utils import now_datetime as frappe_now_datetime

from crm.fcrm.permissions import has_permission as has_student_permission
from crm.fcrm.record_retention import technical_retention_until

_EVENT_PATHS = {
	"nba.evaluation.requested": "/api/v1/insight/nba-evaluation",
	"recommendation.decided.v1": "/api/v1/insight/recommendation-decision",
	"action.outcome_recorded.v1": "/api/v1/insight/action-outcome",
	"student.score_input_changed.v1": "/api/v1/insight/score-input-v1",
	"scoring.policy_changed.v1": "/api/v1/insight/scoring-policy-changed",
}
_EXPECTED_CONTRACT_VERSIONS = {
	"recommendation.decided.v1": 1,
	"action.outcome_recorded.v1": 1,
	"student.score_input_changed.v1": 1,
	"scoring.policy_changed.v1": 1,
}
_MAX_DELIVERY_ATTEMPTS = 10
_LEASE_SECONDS = 120
_AGENT_MANIFEST_CACHE_KEY = "crm_agents:contract_manifest:v1"
_AGENT_MANIFEST_CACHE_TTL_SECONDS = 60
SLA_NOTIFICATION_EVENT = "student.sla.notification.v1"
SLA_DIGEST_EVENT = "student.sla.digest.v1"
_SLA_OUTBOX_FIELDS = {"source_doctype", "source_event", "delivery_key", "channel", "recipient_user", "recipient_role", "payload", "correlation_token", "retention_until", "legal_hold"}


def _test_seam_active() -> bool:
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
	configured = frappe.conf.get("crm_playwright_test_clock") if _test_seam_active() else None
	return get_datetime(configured) if configured else frappe_now_datetime()


def _record_test_delivery(event, body: bytes) -> None:
	"""Persist only redacted metadata; test transport never opens a socket."""
	if not _test_seam_active():
		frappe.throw("TEST_SEAM_DISABLED", frappe.ValidationError)
	key = f"crm_playwright_test_delivery:{frappe.conf.get('crm_playwright_e2e_run_id')}:{event.name}"
	frappe.cache().set_value(key, {"event": event.name, "event_type": event.event_type, "bytes": len(body), "external_url": False})


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


def record_nba_evaluation_event(evaluation) -> str:
	"""Publish an identity-only signal for a durable NBA Evaluation run.

	The payload carries no CRM data. The agent claims the run by name and reads
	the authoritative evaluation input through a fenced Frappe service command.
	Dedup is by ``delivery_key`` so a burst of requests for one evaluation
	identity collapses into a single pending outbox row.
	"""
	delivery_key = f"nba-evaluation:{evaluation.name}"
	fields = _event_fields()
	existing = (
		frappe.db.get_value("CRM Agent Event", {"delivery_key": delivery_key}, "name")
		if "delivery_key" in fields
		else None
	)
	if existing:
		return existing
	event = frappe.get_doc(
		{
			"doctype": "CRM Agent Event",
			"event_id": str(uuid.uuid4()),
			"event_type": "nba.evaluation.requested",
			"aggregate_doctype": "CRM NBA Evaluation",
			"aggregate_name": evaluation.name,
			"source_revision": str(evaluation.evaluation_key),
			"contract_version": 1,
			"occurred_at": now_datetime(),
			"status": "pending",
			"next_attempt_at": now_datetime(),
			"delivery_key": delivery_key,
			"retention_until": _retention_until(),
		}
	)
	try:
		event.insert(ignore_permissions=True)
	except Exception as exc:
		if "duplicate" not in str(exc).casefold() and "unique" not in str(exc).casefold():
			raise
		existing = frappe.db.get_value("CRM Agent Event", {"delivery_key": delivery_key}, "name")
		if not existing:
			raise
		return existing
	_enqueue_delivery(event)
	return event.name


def record_domain_reevaluation_trigger(student: str, *, trigger: str) -> dict:
	"""Admit a Frappe-side domain event (student state change, new
	interaction, ...) as an NBA re-evaluation trigger.

	This is the domain-event counterpart of the WAIT ``revisit_at`` time
	trigger handled by the scheduled ``reconcile_due_reevaluations``: a burst
	of domain events for one student/identity never creates more than one
	active ``CRM NBA Evaluation``. Coalescing itself is delegated to
	``crm.fcrm.nba_evaluations.request_domain_reevaluation``, which reuses the
	Student-row-locked, single-active-run-per-identity primitive already used
	by every other NBA Evaluation entry point -- a domain event for a student
	that already has a queued/running (or identity-unchanged terminal)
	Evaluation is a no-op merge into that run, not a duplicate concurrent one.

	Feature-gated and off by default; a caller with the flag disabled always
	gets a safe no-op receipt instead of a failure.
	"""
	if frappe.conf.get("crm_nba_domain_reevaluation_enabled", 0) in (0, "0", False):
		return {"enabled": False, "created": None, "coalesced": False, "matched_waits": 0}
	if not isinstance(student, str) or not student.strip():
		return {"enabled": True, "created": None, "coalesced": False, "matched_waits": 0}
	trigger_name = str(trigger or "").strip()
	if not trigger_name:
		return {"enabled": True, "created": None, "coalesced": False, "matched_waits": 0}

	from crm.fcrm.nba_evaluations import request_domain_reevaluation

	return request_domain_reevaluation(student.strip(), trigger_reason=trigger_name)


def dispatch_interaction_domain_reevaluation(doc, method=None) -> None:
	"""``doc_events`` hook: a new/updated ``CRM Interaction`` is a domain event
	for NBA re-evaluation, the counterpart of ``admit_interaction`` in
	``crm.services.admission_event_policy`` for scoring admission.

	Best-effort and feature-gated (``record_domain_reevaluation_trigger`` is a
	safe no-op while ``crm_nba_domain_reevaluation_enabled`` is unset): a
	failure here must never abort the Interaction write it hangs off.
	"""
	student = doc.get("student")
	if not student:
		return
	try:
		record_domain_reevaluation_trigger(student, trigger="interaction")
	except Exception:
		frappe.log_error(title="NBA domain re-evaluation dispatch failed", message=f"interaction={doc.name}")


def dispatch_intent_domain_reevaluation(doc, method=None) -> None:
	"""``doc_events`` hook: a new/updated ``CRM Intent`` is a domain event for
	NBA re-evaluation, the counterpart of ``admit_intent`` in
	``crm.services.admission_event_policy`` for scoring admission.

	Best-effort and feature-gated; a failure here must never abort the Intent
	write it hangs off.
	"""
	student = doc.get("student")
	if not student:
		return
	try:
		record_domain_reevaluation_trigger(student, trigger="intent")
	except Exception:
		frappe.log_error(title="NBA domain re-evaluation dispatch failed", message=f"intent={doc.name}")


def record_score_input_event(student: str, revision: int, *, event_id: str | None = None) -> str:
	"""Coalesce only an undispatched scoring event; never rewrite a claim.

	Uses the shared `CRM Agent Event` outbox with its own
	`event_type`/`source_revision_bigint` lineage, so a burst of
	Interaction/Intent/Student writes for one student collapses into a single
	pending scoring event. The `event_type` filter partitions it into an
	independent scoring namespace.
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
	if event.event_type == "student.score_input_changed.v1":
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


def _check_agent_contract_version(event) -> bool:
	"""Validate the producer/consumer version before webhook delivery.

	When the deployment has configured the crm-agents API key, prefer the
	producer's cached manifest.  The local map remains a safe fallback while
	the BFF is unavailable or during older deployments that predate the
	manifest endpoint.
	"""
	expected = _EXPECTED_CONTRACT_VERSIONS.get(event.event_type)
	manifest = _fetch_agent_contract_manifest()
	if manifest is not None:
		advertised = {
			item.get("event_type"): item.get("contract_version")
			for item in manifest.get("events", [])
			if isinstance(item, dict)
		}
		if event.event_type not in advertised:
			frappe.logger("crm.api.agent_events").warning(
				"AGENT_CONTRACT_VERSION_MISMATCH event=%s event_type=%s expected=unsupported actual=%s",
				event.name,
				event.event_type,
				event.contract_version,
			)
			return False
		expected = advertised[event.event_type]
	if expected is None:
		return True
	try:
		actual = int(event.contract_version)
	except (TypeError, ValueError):
		actual = None
	if actual == expected:
		return True
	frappe.logger("crm.api.agent_events").warning(
		"AGENT_CONTRACT_VERSION_MISMATCH event=%s event_type=%s expected=%s actual=%s",
		event.name,
		event.event_type,
		expected,
		actual,
	)
	return False


def _fetch_agent_contract_manifest() -> dict | None:
	"""Fetch and cache the producer contract without affecting delivery flow."""
	base_url = frappe.conf.get("crm_agents_url")
	api_key = frappe.conf.get("crm_agents_api_key")
	if not isinstance(base_url, str) or not base_url.strip() or not isinstance(api_key, str) or not api_key:
		return None
	cache = frappe.cache()
	cached = cache.get_value(_AGENT_MANIFEST_CACHE_KEY)
	if isinstance(cached, dict):
		return cached
	try:
		response = requests.get(
			f"{base_url.rstrip('/')}/api/v1/contract-manifest",
			headers={"X-API-Key": api_key, "Accept": "application/json"},
			timeout=2,
		)
		response.raise_for_status()
		manifest = response.json()
		if not isinstance(manifest, dict) or not isinstance(manifest.get("events"), list):
			raise ValueError("crm-agents contract manifest has an invalid shape")
		cache.set_value(
			_AGENT_MANIFEST_CACHE_KEY,
			manifest,
			expires_in_sec=_AGENT_MANIFEST_CACHE_TTL_SECONDS,
		)
		return manifest
	except Exception as exc:
		frappe.logger("crm.api.agent_events").warning(
			"AGENT_CONTRACT_MANIFEST_UNAVAILABLE url=%s error=%s",
			base_url,
			type(exc).__name__,
		)
		return None


def _complete_delivery(event, lease_id: str, *, status: str = "delivered", error: str | None = None) -> None:
	fields = _event_fields()
	where = "name = %(name)s" + (" and lease_id = %(lease_id)s" if "lease_id" in fields else "")
	values = {"name": event.name, "lease_id": lease_id, "at": now_datetime(), "error": error}
	frappe.db.sql(
		"update `tabCRM Agent Event` set status = %(status)s, delivered_at = %(at)s, last_error = %(error)s where " + where,
		{**values, "status": status},
	)


def _quiesce_contract_mismatch(event) -> None:
	"""Stop delivery until an incompatible producer/consumer is repaired."""
	frappe.db.sql(
		"UPDATE `tabCRM Agent Event` SET status = 'quiesced', last_error = %(error)s "
		"WHERE name = %(name)s AND status IN ('pending', 'processing')",
		{
			"name": event.name,
			"error": "CONTRACT_VERSION_MISMATCH",
		},
	)


def _require_contract_replay_operator() -> None:
	"""Only an operator may release events held for contract repair."""
	if frappe.session.user == "Administrator":
		return
	if "System Manager" not in set(frappe.get_roles()):
		frappe.throw(
			"Only a System Manager may replay quiesced agent events.",
			frappe.PermissionError,
		)


@frappe.whitelist(methods=["POST"])
def requeue_quiesced_agent_events(event_names=None) -> dict:
	"""Revalidate and explicitly requeue contract-quiesced webhook events.

	Events are never released merely because a deployment changed. The operator
	action rechecks the live manifest first, clears only the exact mismatch
	marker, and schedules delivery after the database update.
	"""
	_require_contract_replay_operator()
	if isinstance(event_names, str):
		try:
			event_names = frappe.parse_json(event_names)
		except Exception:
			frappe.throw("event_names must be a JSON array.", frappe.ValidationError)
	if event_names is not None and (
		not isinstance(event_names, list)
		or len(event_names) > 100
		or any(not isinstance(name, str) or not name.strip() for name in event_names)
	):
		frappe.throw("event_names must be a list of at most 100 names.", frappe.ValidationError)
	filters = {"status": "quiesced", "last_error": "CONTRACT_VERSION_MISMATCH"}
	if event_names:
		filters["name"] = ["in", event_names]
	names = frappe.get_all(
		"CRM Agent Event",
		filters=filters,
		pluck="name",
		limit_page_length=100,
		ignore_permissions=True,
	)
	requeued = 0
	blocked = 0
	for name in names:
		event = frappe.get_doc("CRM Agent Event", name)
		if not _check_agent_contract_version(event):
			blocked += 1
			continue
		fields = _event_fields()
		reset_columns = [
			"status = 'pending'",
			"next_attempt_at = %(now)s",
			"last_error = NULL",
		]
		# Keep the operator recovery endpoint usable during a rolling migration:
		# old Agent Event tables may not have received the fencing columns yet.
		if "lease_id" in fields:
			reset_columns.append("lease_id = NULL")
		if "lease_expires_at" in fields:
			reset_columns.append("lease_expires_at = NULL")
		frappe.db.sql(
			"UPDATE `tabCRM Agent Event` SET "
			+ ", ".join(reset_columns)
			+ " WHERE name = %(name)s AND status = 'quiesced'"
			+ " AND last_error = 'CONTRACT_VERSION_MISMATCH'",
			{"name": name, "now": now_datetime()},
		)
		if frappe.db.sql("SELECT ROW_COUNT() AS affected", as_dict=True)[0].affected == 1:
			requeued += 1
			_enqueue_delivery(frappe.get_doc("CRM Agent Event", name))
	return {"requeued": requeued, "blocked": blocked}


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
		if str(event.event_type).startswith(("recommendation.", "action.")):
			frappe.throw("CRM Agent Event lease fields are required for fenced delivery.")
	if event.status not in {"pending", "processing"}:
		return
	if event.event_type not in _EVENT_PATHS and (event.get("channel") or "agent_webhook") != "realtime":
		# Events from retired producers are never retried or sent to a new
		# consumer. Keep the outbox row for audit, but make the retirement
		# terminal and explicit.
		frappe.db.sql(
			"UPDATE `tabCRM Agent Event` SET status = 'cancelled', last_error = %(error)s "
			"WHERE name = %(name)s AND status IN ('pending', 'processing')",
			{"name": event.name, "error": "EVENT_TYPE_RETIRED"},
		)
		return
	if (
		(event.get("channel") or "agent_webhook") != "realtime"
		and not _check_agent_contract_version(event)
	):
		# A log-only mismatch check allowed an event with an incompatible payload
		# to cross the HTTP boundary. Quiesce it instead; replay is explicit after
		# the two deployments agree on the contract.
		_quiesce_contract_mismatch(event)
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
	if _test_seam_active():
		_record_test_delivery(event, body)
		_complete_delivery(event, lease_id)
		return
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


def reconcile_score_input_v1(limit: int = 500) -> dict:
	"""Replay `CRM Score Input Change`'s immutable global sequence with a
	durable cursor -- recovers a missed scoring event without reprocessing a
	revision the consumer's inbox high-water already settled."""
	if frappe.conf.get("crm_agents_scoring_reconciliation_enabled", 0) in (0, "0", False):
		return {"discovered": 0, "enabled": False}
	cache_key = "crm_agents_scoring:score-input-cursor"
	last = int(frappe.cache().get_value(cache_key) or 0)
	rows = frappe.get_all(
		"CRM Student Revision Journal",
		filters={"stream": "scoring", "event_type": "score_input_changed", "stream_sequence": [">", last]},
		fields=["name", "student", "revision", "stream_sequence", "event_id"],
		order_by="stream_sequence asc",
		limit_page_length=min(int(limit), 1000),
	)
	for row in rows:
		record_score_input_event(row.student, int(row.revision), event_id=row.event_id)
	if rows:
		frappe.cache().set_value(cache_key, int(rows[-1].stream_sequence))
	return {"discovered": len(rows), "oldest_unchecked": rows[0].stream_sequence if rows else None}
