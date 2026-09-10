"""Shared validation for the separate Need and Tag catalogues."""

import re

import frappe

from crm.fcrm.segment_lifecycle import TRANSITIONS
from crm.fcrm.segment_rules import bounded_text, fail

GROUP_DOCTYPES = {
	"need": "CRM Need Group",
	"tag": "CRM Tag Group",
}
TERM_DOCTYPES = {
	"need": "CRM Need",
	"tag": "CRM Tag",
}


def require_admin():
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		fail("Only administrators can manage Need and Tag definitions.", "FORBIDDEN", permission=True)


def normalize_group_code(value):
	code = re.sub(r"[^A-Z0-9_]", "_", str(value or "").strip().upper())
	code = re.sub(r"_+", "_", code).strip("_")
	if not code:
		code = "DEFAULT"
	if not code[0].isalpha():
		code = f"GROUP_{code}"
	return code[:100]


def validate_group(doc, kind):
	require_admin()
	if kind not in GROUP_DOCTYPES:
		fail("kind must be need or tag.")
	doc.code = bounded_text(doc.code, "code", limit=100)
	if not re.fullmatch(r"[A-Z][A-Z0-9_]*", doc.code):
		fail("Group codes must use uppercase letters, digits and underscores.")
	doc.label = bounded_text(doc.label, "label")
	doc.description = bounded_text(doc.get("description"), "description", limit=2000, optional=True)
	doc.status = doc.get("status") or "draft"
	if doc.status not in TRANSITIONS:
		fail("Unknown group status.")
	if isinstance(doc.sort_order, bool) or int(doc.sort_order or 0) < 0:
		fail("sort_order must be a non-negative integer.")
	doc.sort_order = int(doc.sort_order or 0)
	before = doc.get_doc_before_save()
	if before:
		if before.status == "archive":
			fail("Archived groups are immutable.")
		if before.code != doc.code:
			fail("Group codes are immutable; change the label instead.")
		if doc.status != before.status and doc.status not in TRANSITIONS[before.status]:
			fail("Invalid group status transition.")
		doc.revision = int(before.revision or 0) + 1
	else:
		if doc.status != "draft":
			fail("New groups must start as draft.")
		doc.revision = 0


def validate_entry(doc, kind):
	require_admin()
	if kind not in TERM_DOCTYPES:
		fail("kind must be need or tag.")
	doc.code = bounded_text(doc.code, "code", limit=100)
	if not re.fullmatch(r"[A-Z][A-Z0-9_]*", doc.code):
		fail("Term codes must use uppercase letters, digits and underscores.")
	doc.label = bounded_text(doc.label, "label")
	doc.group = bounded_text(doc.get("group"), "group")
	if not frappe.db.exists(GROUP_DOCTYPES[kind], doc.group):
		fail(f"Unknown {kind} group.")
	doc.group_name = bounded_text(doc.get("group_name") or doc.group, "group_name")
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


def ensure_group_not_referenced(doc, kind):
	require_admin()
	if doc.status != "draft":
		fail("Archive published groups instead of deleting them.")
	term_doctype = TERM_DOCTYPES[kind]
	if frappe.db.exists(term_doctype, {"group": doc.name}) or frappe.db.exists(
		term_doctype, {"group_name": ["in", [doc.name, doc.label]]}
	):
		fail("This group still contains Need/Tag records; move them before deleting it.")
