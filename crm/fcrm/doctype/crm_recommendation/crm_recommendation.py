import hashlib
from typing import ClassVar

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.permissions import (
	get_permission_query_conditions as get_student_permission_query_conditions,
)
from crm.fcrm.permissions import (
	has_permission as has_student_permission,
)


class CRMRecommendation(Document):
	"""Immutable advice aggregate.

	Only the Phase 6 command service/factory may create or mutate one.  The
	flag is deliberately internal rather than a field a Desk/API caller can set.
	It is the controller-level backstop while legacy DocPerm rows are retired.
	"""

	_PRODUCER_FIELDS = (
		"student", "rule_key", "source_intent_id", "condition_version", "context_hash",
		"policy_version", "producer_id", "producer_revision", "priority",
		"expires_at", "recommended_action", "recommended_timing", "cta",
		"talking_points", "reason", "evidence",
	)
	_DECISION_FIELDS = (
		"status", "decision_reason", "revisit_at", "decision_revision",
		"decision_actor", "decision_at", "decision_scope", "decision_correlation_id",
		"decision_idempotency_key", "supersedes_decision_event",
	)
	_ALLOWED_TRANSITIONS: ClassVar = {
		"new": {"acknowledged", "accepted", "rejected", "deferred", "expired", "superseded"},
		"acknowledged": {"accepted", "rejected", "deferred", "expired", "superseded"},
		"deferred": {"accepted", "rejected", "expired", "superseded"},
	}
	_LEGACY_ONLY_STATUSES: ClassVar = {"dismissed", "modified"}

	def _from_command(self):
		return bool(getattr(self.flags, "from_phase6_command", False) or getattr(self.flags, "phase6_break_glass", False))

	def validate(self):
		"""Keep legacy rows readable while rejecting illegal lifecycle rewrites."""
		self.worklist_priority_rank = {"high": 0, "medium": 1, "low": 2}.get(self.priority, 99)
		# A null recommendation time means no fabricated urgency. Its sortable
		# projection deliberately lands after scheduled work of the same rank.
		self.worklist_timing_sort = self.recommended_timing or "9999-12-31 23:59:59.999999"
		before = self.get_doc_before_save()
		if self.is_new():
			if not self._from_command():
				frappe.throw(_("CRM Recommendations may only be created by the approved server-side producer."))
			if self.status in self._LEGACY_ONLY_STATUSES:
				frappe.throw(_("Legacy CRM Recommendation status {0} cannot be created.").format(self.status))
			return
		if not before:
			return
		changed_fields = {field for field in self._PRODUCER_FIELDS + self._DECISION_FIELDS if self.get(field) != before.get(field)}
		if changed_fields and not self._from_command():
			frappe.throw(_("CRM Recommendation decisions and producer data must use a Phase 6 server command."))
		immutable_changes = [field for field in self._PRODUCER_FIELDS if self.get(field) != before.get(field)]
		if immutable_changes:
			frappe.throw(_("CRM Recommendation producer fields are immutable: {0}").format(", ".join(immutable_changes)))
		if before.status in self._LEGACY_ONLY_STATUSES and self.status != before.status:
			frappe.throw(_("Legacy CRM Recommendation status {0} is read-only pending migration.").format(before.status))
		if before.status == self.status:
			return
		allowed = self._ALLOWED_TRANSITIONS.get(before.status, set())
		if self.status not in allowed:
			frappe.throw(_("Illegal CRM Recommendation transition: {0} -> {1}").format(before.status, self.status))
		if self.status == "rejected" and not self.decision_reason:
			frappe.throw(_("A decision reason is required when rejecting a recommendation."))
		if self.status == "deferred" and not (self.revisit_at or self.decision_reason):
			frappe.throw(_("A deferred recommendation needs a UTC revisit time or an archival reason."))
		if self.status != "deferred" and self.revisit_at:
			frappe.throw(_("revisit_at is only valid for a deferred recommendation."))
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
			"e2e_capture_readiness", "e2e_capture_cross_campus"
		} else "REC-"
		self.name = f"{prefix}{digest}"


def get_permission_query_conditions(user=None):
	"""Project the canonical CRM Student own/team/director scope onto advice."""
	if not user:
		user = frappe.session.user
	student_condition = get_student_permission_query_conditions("CRM Student", user=user)
	if student_condition is None:
		return None
	if student_condition == "1=0":
		return "1=0"
	return (
		"`tabCRM Recommendation`.student in ("
		"select `tabCRM Student`.name from `tabCRM Student` "
		f"where ({student_condition})"
		")"
	)


def has_permission(doc, user=None, permission_type=None):
	"""Direct-GET-by-name guard using the same current Student scope."""
	if not user:
		user = frappe.session.user

	student = doc.get("student") if isinstance(doc, dict) else getattr(doc, "student", None)
	if not student:
		return False

	try:
		student_doc = frappe.get_doc("CRM Student", student)
		return has_student_permission(student_doc, user=user, permission_type=permission_type)
	except Exception:
		return False
