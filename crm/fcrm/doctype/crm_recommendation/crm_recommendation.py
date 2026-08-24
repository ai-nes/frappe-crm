import hashlib

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime
from crm.fcrm.permissions import (
	get_permission_query_conditions as get_student_permission_query_conditions,
)


class CRMRecommendation(Document):
	_ALLOWED_TRANSITIONS = {
		"new": {"acknowledged", "dismissed", "accepted", "rejected", "deferred", "modified", "expired", "superseded"},
		"acknowledged": {"dismissed", "accepted", "rejected", "deferred", "modified", "expired", "superseded"},
		"deferred": {"accepted", "rejected", "modified", "expired", "superseded"},
		"accepted": {"modified", "expired", "superseded"},
		"modified": {"expired", "superseded"},
	}

	def validate(self):
		"""Keep legacy rows readable while rejecting illegal lifecycle rewrites."""
		self.worklist_priority_rank = {"high": 0, "medium": 1, "low": 2}.get(self.priority, 99)
		# A null recommendation time means no fabricated urgency. Its sortable
		# projection deliberately lands after scheduled work of the same rank.
		self.worklist_timing_sort = self.recommended_timing or "9999-12-31 23:59:59.999999"
		before = self.get_doc_before_save()
		if not before or before.status == self.status:
			return
		allowed = self._ALLOWED_TRANSITIONS.get(before.status, set())
		if self.status not in allowed:
			frappe.throw(_("Illegal CRM Recommendation transition: {0} -> {1}").format(before.status, self.status))
		if self.status in {"rejected", "deferred"} and not self.decision_reason:
			frappe.throw(_("A decision reason is required when rejecting or deferring a recommendation."))
	def autoname(self):
		"""Deterministic name = hash(student, rule_key, source_intent_id, condition_version, context revision).

		Naming the record by a hash of these immutable fields, rather than a random/
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
		# The E2E fixture is reset/reseeded on a shared development site where
		# Student and Intent use monotonic naming series.  Its context hash is a
		# fixed fixture key, so preserve a stable Recommendation/Action identity
		# across resets without changing production recommendation fingerprints.
		if self.rule_key == "e2e_capture_readiness" and self.context_hash:
			fingerprint_parts = ["e2e_capture", self.context_hash]
		else:
			fingerprint_parts = [
				self.student,
				self.rule_key,
				self.source_intent_id,
				str(self.condition_version),
			]
		# Legacy rows keep their original four-part identity. A versioned context
		# adds one immutable revision component.
		if self.context_hash and self.rule_key != "e2e_capture_readiness":
			fingerprint_parts.append(self.context_hash)
		fingerprint = "|".join(fingerprint_parts)
		digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:24]
		# The reset API accepts only this fixture namespace, never production
		# REC-* IDs. Keep its marker in the durable aggregate identity so an
		# agent-side cleanup can prove that an inbox event belongs to the fixture.
		prefix = "REC-E2E-FPT-2026-" if self.rule_key in {
			"e2e_capture_readiness",
			"e2e_capture_cross_campus",
		} else "REC-"
		self.name = f"{prefix}{digest}"


def get_permission_query_conditions(user=None):
	"""LIST-view guard derived from the canonical CRM Student scope.

	Recommendations are batch-written by a service account, so ownership on
	the recommendation itself is not an authorization signal.  The underlying
	Student permission condition is the single row-scope source for Sale,
	Lead Sales, Marketing, and oversight roles; this prevents the recommendation
	worklist from widening Lead Sales beyond its own teams.
	"""
	if not user:
		user = frappe.session.user

	student_condition = get_student_permission_query_conditions("CRM Student", user=user)
	if student_condition is None:
		return None
	return (
		"`tabCRM Recommendation`.student in ("
		"select `tabCRM Student`.name from `tabCRM Student` "
		f"where {student_condition}"
		")"
	)


def on_status_decided(doc, method=None):
	"""Sales just decided Accept/Reject/Defer/Modify in the Frappe UI (a plain
	write to `status`) — when the decision is accepted/modified, tell
	crm-agents in the background so it can create the CRM Sales Action row
	that will track execution/outcome for it.

	Fires on every save, not just this one, so it detects the actual transition.
	The Sales Action and outbox row are written in this same Frappe transaction;
	the asynchronous delivery only signals crm-agents to re-read authoritative
	CRM data.
	"""
	before = doc.get_doc_before_save()
	previous_status = before.status if before else None
	if doc.status == previous_status or doc.status not in ("accepted", "modified"):
		return
	_create_sales_action(doc)
	from crm.api.agent_events import record_agent_event

	record_agent_event("recommendation.decided.v1", doc)


def _create_sales_action(recommendation) -> str:
	"""Create the one linked Sales Action before committing the decision."""
	existing = frappe.db.get_value("CRM Sales Action", {"recommendation": recommendation.name}, "name")
	if existing:
		return existing
	action = frappe.get_doc(
		{
			"doctype": "CRM Sales Action",
			"recommendation": recommendation.name,
			"student": recommendation.student,
			"action_type": recommendation.recommended_action,
			"execution_status": "planned",
			"created_at": now_datetime(),
		}
	)
	action.insert(ignore_permissions=True)
	return action.name


def has_permission(doc, user=None, permission_type=None):
	"""Direct-GET-by-name guard using the same Student scope as list views."""
	if not user:
		user = frappe.session.user

	student = doc.get("student") if isinstance(doc, dict) else getattr(doc, "student", None)
	if not student:
		return False

	student_condition = get_student_permission_query_conditions("CRM Student", user=user)
	if student_condition is None:
		return True
	return bool(
		frappe.db.sql(
			"select name from `tabCRM Student` where name = %s and (" + student_condition + ") limit 1",
			(student,),
		)
	)
