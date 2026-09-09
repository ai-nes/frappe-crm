"""Shared validation for the separate Need and Tag catalogues."""

import re

import frappe

from crm.fcrm.segment_lifecycle import TRANSITIONS
from crm.fcrm.segment_rules import bounded_text, fail


def require_admin():
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		fail("Only administrators can manage Need and Tag definitions.", "FORBIDDEN", permission=True)


def validate_entry(doc, kind):
	require_admin()
	doc.code = bounded_text(doc.code, "code", limit=100)
	if not re.fullmatch(r"[A-Z][A-Z0-9_]*", doc.code):
		fail("Term codes must use uppercase letters, digits and underscores.")
	doc.label = bounded_text(doc.label, "label")
	doc.group_name = bounded_text(doc.group_name, "group_name")
	doc.description = bounded_text(doc.get("description"), "description", limit=2000, optional=True)
	doc.status = doc.get("status") or "draft"
	if doc.status not in TRANSITIONS:
		fail("Unknown term status.")
	if kind == "tag":
		reserved = {
			"HIGH",
			"MEDIUM",
			"LOW",
			"NEW",
			"QUALIFIED",
			"COUNSELING",
			"APPLIED",
			"ADMITTED",
			"ENROLLED",
			"LOST",
		}
		reserved.update(frappe.get_all("CRM Enrollment Status", pluck="name"))
		if doc.code in reserved or any(
			word in doc.code for word in ("POTENTIAL", "INTENT", "ADMISSION_STAGE")
		):
			fail("Tags cannot replace structured Stage, Potential or Intent classifications.")
	before = doc.get_doc_before_save()
	if before:
		if before.status == "archive":
			fail("Archived terms are immutable.")
		if self_code := before.get("code"):
			if doc.code != self_code:
				fail("Term codes are immutable; change the label instead.")
		if doc.status != before.status and doc.status not in TRANSITIONS[before.status]:
			fail("Invalid term status transition.")
		doc.revision = int(before.revision or 0) + 1
	else:
		if doc.status != "draft":
			fail("New terms must start as draft.")
		doc.revision = 0


def ensure_not_referenced(doc, assignment_doctype, assignment_field):
	require_admin()
	if doc.status != "draft":
		fail("Archive published terms instead of deleting them.")
	if frappe.db.exists(assignment_doctype, {assignment_field: doc.name}):
		fail("This term is assigned to a Student; archive it instead.")
	for rules in frappe.get_all("CRM Segment", pluck="filters"):
		try:
			groups = (frappe.parse_json(rules) or {}).get("groups", [])
		except (ValueError, AttributeError):
			continue
		for group in groups:
			for condition in group.get("conditions", []):
				if condition.get("value") and doc.name in condition["value"]:
					fail("This term is referenced by a Segment; archive it instead.")
