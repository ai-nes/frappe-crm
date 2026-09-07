"""Shared behaviour for flat controlled-vocabulary lookup doctypes.

Each lookup replaces one former ``CRM Term`` category. A row stores an immutable
UPPER_SNAKE ``code`` machine key (what consumer Link fields and the AI service
match on) and a Vietnamese ``display_name`` shown in every UI. Values are managed
directly by System Manager - no approval workflow - and seeded from
``crm.fcrm.reference_catalog``.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document

from crm.fcrm.action_type_catalog import is_valid_configuration_code

# (consumer doctype, fieldname) pairs that Link to each lookup. Checked before a
# value may be deleted so a live reference is never orphaned.
LOOKUP_CONSUMERS: dict[str, tuple[tuple[str, str], ...]] = {
	"CRM Lost Reason": (),
	"CRM Campaign Type": (("CRM Campaign", "campaign_type"),),
	"CRM Intent Type": (("CRM Intent", "intent_type"), ("CRM Score Signal", "intent_type")),
	"CRM Interaction Type": (
		("CRM Interaction", "interaction_type"),
		("CRM Score Signal", "interaction_term"),
	),
	"CRM School Type": (("CRM High School", "school_type"),),
	"CRM School Area": (("CRM High School", "school_area"),),
	"CRM Stakeholder Role": (("CRM School Stakeholder", "stakeholder_role"),),
	"CRM School Activity Type": (("CRM School Activity", "activity_type"),),
	"CRM Major Group": (("CRM Major", "major_group"),),
	"CRM Aspiration": (("CRM Student", "aspiration"), ("CRM Lead", "aspiration")),
	"CRM Region": (
		("CRM Province", "region"),
		("CRM Territory", "region"),
		("CRM Planning Scope", "region"),
	),
	"CRM Enrollment Status": (
		("CRM Student", "enrollment_status"),
		("CRM Lead", "enrollment_status"),
	),
	"CRM Admission Method": (
		("CRM Admission Offering", "admission_method"),
		("CRM Admission Application", "admission_method"),
	),
}


class LookupDocument(Document):
	"""Base controller: immutable code, required display name, guarded delete."""

	def validate(self):
		if not is_valid_configuration_code(self.code):
			frappe.throw(
				"Code must be UPPER_SNAKE_CASE (uppercase letters, digits, underscore).",
				frappe.ValidationError,
			)
		if not (self.display_name or "").strip():
			frappe.throw("Display name is required.", frappe.ValidationError)
		if not self.is_new() and self.has_value_changed("code"):
			frappe.throw("A lookup code is immutable.", frappe.PermissionError)

	def on_trash(self):
		for consumer_doctype, fieldname in LOOKUP_CONSUMERS.get(self.doctype, ()):
			if frappe.db.exists("DocType", consumer_doctype) and frappe.db.exists(
				consumer_doctype, {fieldname: self.name}
			):
				frappe.throw(
					f"Cannot delete {self.doctype} {self.name}: still referenced by "
					f"{consumer_doctype}.{fieldname}. Disable it instead.",
					frappe.ValidationError,
				)
