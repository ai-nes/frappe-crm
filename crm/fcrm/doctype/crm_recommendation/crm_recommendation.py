import hashlib

import frappe
from frappe import _
from frappe.model.document import Document


class CRMRecommendation(Document):
	def autoname(self):
		"""Deterministic name = hash(student, rule_key, source_intent_id, condition_version).

		Naming the record by a hash of these four fields, rather than a random/
		series name, means a concurrent double-run of the nightly batch racing to
		insert the same fingerprint fails on the SECOND insert with a duplicate
		primary-key error instead of silently creating two rows. Query-then-insert
		alone (a fast-path optimization the batch pipeline also does) is not
		race-safe by itself — this autoname is the actual DB-enforced backstop.
		"""
		required = {
			"student": self.student,
			"rule_key": self.rule_key,
			"source_intent_id": self.source_intent_id,
		}
		missing = [field for field, value in required.items() if not value]
		if missing or self.condition_version is None:
			frappe.throw(
				_("CRM Recommendation requires student, rule_key, source_intent_id and condition_version before it can be named"),
			)
		fingerprint = "|".join([
			self.student,
			self.rule_key,
			self.source_intent_id,
			str(self.condition_version),
		])
		digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:24]
		self.name = f"REC-{digest}"


def _crm_staff_campus(user: str) -> tuple[str | None, str | None]:
	"""Return (crm_staff_name, campus) for `user`, or (None, None) if unmapped."""
	crm_staff_name = frappe.db.get_value("CRM Staff", {"user": user}, "name")
	if not crm_staff_name:
		return None, None
	campus = frappe.db.get_value("CRM Staff", crm_staff_name, "campus")
	return crm_staff_name, campus


def get_permission_query_conditions(user=None):
	"""LIST-view guard: only rows for students whose assigned_to falls in the
	requesting user's own campus are visible.

	Mirrors crm_contact.get_permission_query_conditions's campus-based
	filtering — CRM Recommendation is batch-written by a service account
	(the record `owner` is never the assigned Sale/CTV-Sale), so `if_owner`
	cannot be used here: it would filter on `owner == current_user` and hide
	every recommendation from every sales/marketing role, regardless of
	whether the underlying student is assigned to them.
	"""
	if not user:
		user = frappe.session.user

	if "System Manager" in frappe.get_roles(user) or "CRM Manager" in frappe.get_roles(user):
		return None

	_crm_staff_name, campus = _crm_staff_campus(user)
	if not campus:
		return "1=0"

	crm_staff_in_campus = frappe.db.get_all(
		"CRM Staff",
		filters={"campus": campus},
		pluck="name",
	)
	if not crm_staff_in_campus:
		return "1=0"

	escaped = ", ".join(frappe.db.escape(s) for s in crm_staff_in_campus)
	return (
		"`tabCRM Recommendation`.student in ("
		"select `tabCRM Student`.name from `tabCRM Student` "
		f"where `tabCRM Student`.assigned_to in ({escaped})"
		")"
	)


def on_status_decided(doc, method=None):
	"""Sales just decided Accept/Reject/Defer/Modify in the Frappe UI (a plain
	write to `status`) — when the decision is accepted/modified, tell
	crm-agents in the background so it can create the CRM Sales Action row
	that will track execution/outcome for it.

	Fires on every save, not just this one, so it must detect the actual
	transition itself via `get_doc_before_save()` rather than assume it only
	runs once. Bypassable like any Frappe hook (a direct `db_set` skips it
	entirely) — crm-agents' own reconciliation sweep is the correctness
	backstop for whatever this hook misses, not this call alone.
	"""
	before = doc.get_doc_before_save()
	previous_status = before.status if before else None
	if doc.status == previous_status or doc.status not in ("accepted", "modified"):
		return
	frappe.enqueue(
		"crm.fcrm.doctype.crm_recommendation.crm_recommendation.notify_crm_agents_of_decision",
		queue="short",
		enqueue_after_commit=True,
		recommendation=doc.name,
		student=doc.student,
		action_type=doc.recommended_action,
		status=doc.status,
		decision_reason=doc.decision_reason,
	)


def notify_crm_agents_of_decision(recommendation, student, action_type, status, decision_reason=None):
	"""Background job body for on_status_decided — HMAC-signs and POSTs the
	decision to crm-agents' recommendation-decision endpoint, the same
	{timestamp}.{body} HMAC-SHA256 scheme crm-agents itself uses to verify
	the Chatwoot webhook. Never raises: a failed delivery is logged and left
	for crm-agents' reconciliation sweep, not retried here.
	"""
	import hashlib
	import hmac
	import json
	import time

	import requests

	base_url = frappe.conf.get("crm_agents_url")
	secret = frappe.conf.get("crm_agents_webhook_secret")
	if not base_url or not secret:
		frappe.log_error(
			title="crm-agents webhook not configured",
			message="site_config.json is missing crm_agents_url / crm_agents_webhook_secret",
		)
		return

	body = json.dumps({
		"recommendation": recommendation,
		"student": student,
		"action_type": action_type,
		"status": status,
		"decision_reason": decision_reason,
	}).encode("utf-8")
	timestamp = str(int(time.time()))
	signature = hmac.new(secret.encode("utf-8"), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()

	try:
		response = requests.post(
			f"{base_url.rstrip('/')}/api/v1/insight/recommendation-decision",
			data=body,
			headers={
				"Content-Type": "application/json",
				"X-CRM-Signature": f"sha256={signature}",
				"X-CRM-Timestamp": timestamp,
			},
			timeout=10,
		)
		response.raise_for_status()
	except Exception as exc:
		frappe.log_error(
			title="crm-agents recommendation-decision notify failed",
			message=f"recommendation={recommendation}: {exc}",
		)


def has_permission(doc, user=None, permission_type=None):
	"""Direct-GET-by-name guard (also covers report/export and link-lookup reads
	that resolve a specific document rather than running the list query).

	`get_permission_query_conditions` only protects the LIST path — Frappe calls
	this function separately for `frappe.get_doc("CRM Recommendation", name)`,
	so both must independently enforce the same campus scope or a direct GET by
	name bypasses the list filter entirely.
	"""
	if not user:
		user = frappe.session.user

	if "System Manager" in frappe.get_roles(user) or "CRM Manager" in frappe.get_roles(user):
		return True

	student = doc.get("student") if isinstance(doc, dict) else getattr(doc, "student", None)
	if not student:
		return False

	_crm_staff_name, campus = _crm_staff_campus(user)
	if not campus:
		return False

	assigned_to = frappe.db.get_value("CRM Student", student, "assigned_to")
	if not assigned_to:
		return False

	assigned_campus = frappe.db.get_value("CRM Staff", assigned_to, "campus")
	return assigned_campus == campus
