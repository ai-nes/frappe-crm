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
