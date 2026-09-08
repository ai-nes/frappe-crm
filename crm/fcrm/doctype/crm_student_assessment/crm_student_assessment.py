"""Canonical, versioned Student 360 assessment aggregate."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.permissions import (
	get_permission_query_conditions as get_student_permission_query_conditions,
)
from crm.fcrm.permissions import has_permission as has_student_permission

ASSESSMENT_SOURCES = frozenset({"system", "manual"})
ASSESSMENT_STATUSES = frozenset({"proposed", "confirmed", "superseded", "rejected"})
LEVELS = frozenset({"High", "Medium", "Low", "Unknown"})
BARRIERS = frozenset({"Cost", "Capability", "Family", "Information", "Geography", "Competition", "None", "Unknown"})


def parse_evidence(value):
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except (TypeError, ValueError):
			value = [value]
	if not isinstance(value, (list, tuple)):
		value = [value] if value else []
	return [str(item).strip()[:256] for item in value if str(item).strip()][:40]


class CRMStudentAssessment(Document):
	"""Immutable assessment snapshot; commands create a new revision."""

	_IMMUTABLE_FIELDS = (
		"student", "assessment_revision", "assessment_source", "assessed_at",
		"policy_version", "model_version", "interest", "interest_confidence",
		"signal_score", "enrollment_probability", "recommendation", "review_state",
		"fit", "fit_confidence", "primary_barrier", "barrier_confidence",
		"reason", "evidence_references", "supersedes", "confirmed_by", "confirmed_at", "override_reason",
	)

	def _from_command(self):
		return bool(getattr(self.flags, "student_assessment_command", False))

	def validate(self):
		if self.assessment_source not in ASSESSMENT_SOURCES:
			frappe.throw(_("Assessment source must be system or manual."), frappe.ValidationError)
		if self.status not in ASSESSMENT_STATUSES:
			frappe.throw(_("Assessment status is invalid."), frappe.ValidationError)
		if self.interest not in LEVELS or self.fit not in LEVELS:
			frappe.throw(_("Interest and Fit values are invalid."), frappe.ValidationError)
		if self.primary_barrier not in BARRIERS:
			frappe.throw(_("Primary Barrier value is invalid."), frappe.ValidationError)
		for fieldname in ("interest_confidence", "fit_confidence", "barrier_confidence"):
			value = float(self.get(fieldname) or 0)
			if value < 0 or value > 100:
				frappe.throw(_("{0} must be between 0 and 100.").format(fieldname), frappe.ValidationError)
		if not 0 <= float(self.get("enrollment_probability") or 0) <= 100:
			frappe.throw(_("Enrollment probability must be between 0 and 100."), frappe.ValidationError)
		evidence = parse_evidence(self.evidence_references)
		self.evidence_references = json.dumps(evidence, ensure_ascii=False)
		if not evidence:
			frappe.throw(_("At least one assessment evidence reference is required."), frappe.ValidationError)
		if not str(self.reason or "").strip():
			frappe.throw(_("An explainable assessment reason is required."), frappe.ValidationError)
		if self.status == "confirmed" and (not self.confirmed_by or not self.confirmed_at):
			frappe.throw(_("A confirmed assessment requires actor and timestamp."), frappe.ValidationError)
		if self.is_new():
			if not self._from_command():
				frappe.throw(_("Student assessments may only be created by the assessment command."))
			return
		before = self.get_doc_before_save()
		if not before:
			return
		if any(self.get(fieldname) != before.get(fieldname) for fieldname in self._IMMUTABLE_FIELDS) and not self._from_command():
			frappe.throw(_("Assessment evidence and dimensions are immutable; create a new revision."))
		if self.status != before.status and not self._from_command():
			frappe.throw(_("Assessment status changes must use the assessment command."))


def on_doctype_update():
	"""Enforce one revision number per Student after a safe duplicate check."""
	if not frappe.db.table_exists("CRM Student Assessment"):
		return
	if frappe.db.sql("SHOW INDEX FROM `tabCRM Student Assessment` WHERE Key_name = %s", "crm_student_assessment_revision_uniq"):
		return
	duplicates = frappe.db.sql(
		"SELECT student, assessment_revision, COUNT(*) AS row_count FROM `tabCRM Student Assessment` GROUP BY student, assessment_revision HAVING row_count > 1 LIMIT 1",
		as_dict=True,
	)
	if duplicates:
		frappe.log_error("Student assessment revision duplicates require quarantine before the unique index can be created.", "Student 360 assessment revision index")
		return
	frappe.db.sql_ddl(
		"ALTER TABLE `tabCRM Student Assessment` ADD UNIQUE INDEX `crm_student_assessment_revision_uniq` (`student`, `assessment_revision`)"
	)


def get_permission_query_conditions(user=None):
	if not user:
		user = frappe.session.user
	student_condition = get_student_permission_query_conditions("CRM Lead", user=user)
	if student_condition is None:
		return None
	if student_condition == "1=0":
		return "1=0"
	return "`tabCRM Student Assessment`.student in (select `tabCRM Lead`.name from `tabCRM Lead` where ({0}))".format(student_condition)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	if not user:
		user = frappe.session.user
	permission_type = permission_type or ptype
	student = doc.get("student") if isinstance(doc, dict) else getattr(doc, "student", None)
	if not student:
		return False
	try:
		roles = set(frappe.get_roles(user))
		if permission_type in {"create", "write", "delete"}:
			return bool(
				user == "Administrator"
				or "System Manager" in roles
				or ("Admissions Director" in roles and has_student_permission(frappe.get_doc("CRM Lead", student), user=user, permission_type="write"))
			)
		return has_student_permission(frappe.get_doc("CRM Lead", student), user=user, permission_type="read")
	except Exception:
		return False
