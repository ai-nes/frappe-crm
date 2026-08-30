from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, nowdate

from crm.fcrm.admissions_migration import stable_fingerprint
from crm.fcrm.school_domain_permissions import (
	has_school_portfolio_permission,
	school_portfolio_condition,
)

DEFAULT_NE_THRESHOLD = 10
GOVERNANCE_ROLES = frozenset({"Administrator", "System Manager", "Admissions Director"})


def _is_governance_user(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(GOVERNANCE_ROLES & set(frappe.get_roles(user)))


def _metric_filters(doc):
	return {"high_school": doc.high_school, "admission_year": doc.admission_year}


def compute_crm_metrics(high_school, admission_year):
	"""Return distinct CRM funnel measures for one school and admission year."""
	contact_filters = {"high_school": high_school, "admission_year": admission_year}
	student_filters = {"high_school": high_school, "admission_year": admission_year}
	contact_count = frappe.db.count("CRM Contact", contact_filters)
	student_count = frappe.db.count("CRM Student", student_filters)
	applicant_count = frappe.db.count("CRM Contact", {**contact_filters, "lifecycle_stage": "Applicant"})
	enrolled_contacts = frappe.db.count("CRM Contact", {**contact_filters, "lifecycle_stage": "Enrolled"})
	enrolled_students = frappe.db.count("CRM Student", {**student_filters, "lifecycle_stage": "Enrolled"})
	student_names = frappe.get_all("CRM Student", filters=student_filters, pluck="name")
	conversion_count = 0
	if student_names and frappe.db.exists("DocType", "CRM Student Contact Conversion"):
		conversion_count = frappe.db.count(
			"CRM Student Contact Conversion", {"student": ["in", student_names]}
		)
	enrolled_count = max(enrolled_contacts, enrolled_students)
	conversion_rate = (enrolled_count / applicant_count * 100) if applicant_count else 0
	enrollment_rate = (enrolled_count / student_count * 100) if student_count else 0
	return {
		"applicant_count": applicant_count,
		"enrolled_count": enrolled_count,
		"contact_count": contact_count,
		"student_count": student_count,
		"conversion_count": conversion_count,
		"ne_registered": applicant_count,
		"ne_achieved": enrolled_count,
		"conversion_rate": round(conversion_rate, 2),
		"enrollment_rate": round(enrollment_rate, 2),
	}


def _snapshot_for_school(high_school):
	return frappe.get_all(
		"CRM High School Annual Snapshot",
		filters={"high_school": high_school, "verification_status": "Verified", "period_type": "Annual"},
		fields=["name", "admission_year", "key_account_eligible", "snapshot_date", "revision"],
		order_by="admission_year desc, snapshot_date desc, revision desc",
		limit_page_length=1,
	)


def refresh_school_key_account(high_school):
	"""Project latest annual eligibility onto the school master."""
	if not frappe.db.exists("CRM High School", high_school):
		return
	rows = _snapshot_for_school(high_school)
	if not rows:
		frappe.db.set_value(
			"CRM High School",
			high_school,
			{"is_key_account": 0},
			update_modified=False,
		)
		return
	snapshot = rows[0]
	eligible = int(bool(snapshot.key_account_eligible))
	frappe.db.set_value(
		"CRM High School",
		high_school,
		{"is_key_account": eligible},
		update_modified=False,
	)


class CRMHighSchoolAnnualSnapshot(Document):
	_IMMUTABLE_FIELDS = (
		"high_school",
		"admission_year",
		"measured_on",
		"period_type",
		"period",
		"revision",
		"timezone",
		"ne_target",
		"ne_actual",
		"adjusted_ne_threshold",
		"ne_actual_semantics",
		"source_system",
		"source_run",
		"recorded_at",
		"supersedes",
	)

	def before_validate(self):
		if self.adjusted_ne_threshold in (None, ""):
			self.adjusted_ne_threshold = DEFAULT_NE_THRESHOLD
		if not self.snapshot_date:
			self.snapshot_date = nowdate()
		if not self.get("measured_on"):
			self.measured_on = self.snapshot_date
		if not self.get("period_type"):
			self.period_type = "Annual"
		if not self.get("period"):
			self.period = str(self.measured_on)
		if not self.get("revision"):
			self.revision = 1
		if not self.get("timezone"):
			self.timezone = "Asia/Ho_Chi_Minh"
		if not self.get("recorded_at"):
			self.recorded_at = now_datetime()
		if not self.get("source_system"):
			self.source_system = "crm"
		if not self.get("source_run"):
			self.source_run = f"snapshot:{self.high_school}:{self.admission_year}:{self.period}"
		if not self.get("idempotency_fingerprint"):
			self.idempotency_fingerprint = stable_fingerprint(
				"snapshot",
				self.high_school,
				self.admission_year,
				self.period_type,
				self.period,
				self.revision,
				self.source_system,
				self.source_run,
			)
		previous = self.get_doc_before_save()
		if self.high_school and self.admission_year and not (previous and previous.verification_status == "Verified"):
			self._set_crm_metrics()

	def validate(self):
		# The guards are methods on a real Frappe Document.  Keeping the calls
		# capability-based also lets lightweight contract fixtures exercise the
		# lock projection without pretending to be a full Document instance.
		for validator in ("_validate_grain", "_validate_threshold", "_validate_lock"):
			check = getattr(self, validator, None)
			if check:
				check()
		ne_actual = self.get("ne_actual")
		threshold = self.get("adjusted_ne_threshold")
		self.key_account_eligible = int(ne_actual not in (None, "") and int(ne_actual) >= int(threshold))
		if self.get("verification_status") == "Verified" and not self.get("verified_by"):
			self.verified_by = frappe.session.user
			self.verified_at = now_datetime()
		# Frappe Document reserves the ``is_locked`` attribute for its internal
		# file-lock property. Read the DocType field through ``get`` so the
		# governance field remains usable without colliding with that property.
		if self.get("is_locked") and not self.get("locked_by"):
			self.set("locked_by", frappe.session.user)
			self.set("locked_at", now_datetime())
		check = getattr(self, "_validate_immutable_fact", None)
		if check:
			check()

	def on_update(self):
		refresh_school_key_account(self.high_school)

	def after_delete(self):
		"""Reproject only after the deleted snapshot is no longer queryable."""
		refresh_school_key_account(self.high_school)

	def _set_crm_metrics(self):
		for fieldname, value in compute_crm_metrics(self.high_school, self.admission_year).items():
			setattr(self, fieldname, value)

	def _validate_grain(self):
		filters = {
			"high_school": self.get("high_school"),
			"admission_year": self.get("admission_year"),
			"period_type": self.get("period_type"),
			"period": self.get("period"),
			"revision": self.get("revision"),
		}
		if not self.is_new():
			filters["name"] = ["!=", self.get("name")]
		if frappe.db.exists("CRM High School Annual Snapshot", filters):
			frappe.throw("This school snapshot revision already exists.", frappe.DuplicateEntryError)
		if int(self.get("revision") or 0) > 1 and not self.get("supersedes"):
			frappe.throw("A snapshot correction must supersede an earlier revision.", frappe.ValidationError)

	def _validate_immutable_fact(self):
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if previous and any(
			self.get(fieldname) != previous.get(fieldname) for fieldname in self._IMMUTABLE_FIELDS
		):
			frappe.throw("Snapshots are immutable; write a new revision.", frappe.PermissionError)

	def _validate_threshold(self):
		if int(self.adjusted_ne_threshold) < 0:
			frappe.throw("Adjusted NE threshold cannot be negative.", frappe.ValidationError)

	def _validate_lock(self):
		previous = self.get_doc_before_save()
		if not previous:
			if self.get("is_locked") and not _is_governance_user():
				frappe.throw("Only governance roles can lock an annual snapshot.", frappe.PermissionError)
			return
		if previous.verification_status == "Verified" and any(
			previous.get(fieldname) != self.get(fieldname)
			for fieldname in ("high_school", "admission_year", "ne_actual")
		):
			frappe.throw("Verified snapshot identity and source outcomes are immutable.", frappe.PermissionError)
		if previous.get("is_locked") and not _is_governance_user():
			frappe.throw("This annual snapshot is locked by governance.", frappe.PermissionError)
		if not _is_governance_user() and any(
			previous.get(fieldname) != self.get(fieldname)
			for fieldname in ("ne_target", "adjusted_ne_threshold", "is_locked")
		):
			frappe.throw(
				"Only governance roles can change target, threshold or lock state.", frappe.PermissionError
			)

def get_snapshot_metrics(high_school, admission_year):
	return compute_crm_metrics(high_school, admission_year)


# Module-level permission hooks (registered in hooks.py). Kept out of the
# Document subclass so ``has_permission`` never shadows Document.has_permission.
def get_permission_query_conditions(user=None, doctype=None):
	if doctype not in (None, "CRM High School Annual Snapshot"):
		return "1=0"
	return school_portfolio_condition(
		"CRM High School Annual Snapshot", user, school_field="high_school"
	)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	return has_school_portfolio_permission(doc, user, permission_type, ptype)
