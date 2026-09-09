"""Separate Need and Tag assignments, validated on every Student write."""

import frappe

from crm.fcrm.segment_rules import fail


def classification_changed(doc, before):
	if not before:
		return True
	return (
		any(doc.get(field) != before.get(field) for field in ("potential", "intent"))
		or {row.need for row in doc.get("needs", [])} != {row.need for row in before.get("needs", [])}
		or {row.tag for row in doc.get("tags", [])} != {row.tag for row in before.get("tags", [])}
		or {row.term for row in doc.get("classifications", [])}
		!= {row.term for row in before.get("classifications", [])}
	)


def _validate_level(doc, field):
	if doc.get(field) not in (None, "", "HIGH", "MEDIUM", "LOW"):
		fail(f"Unknown {field} level.")


def _validate_assignments(doc, field, doctype, link_field, kind):
	rows = doc.get(field, [])
	if len(rows) > 100 or len({getattr(row, link_field, None) for row in rows}) != len(rows):
		fail(f"Student {kind}s must be unique and contain at most 100 terms.")
	before = doc.get_doc_before_save()
	previous = {getattr(row, link_field): row for row in (before.get(field, []) if before else [])}
	for row in sorted(rows, key=lambda item: getattr(item, link_field, "") or ""):
		term_name = getattr(row, link_field, None)
		term = frappe.get_doc(doctype, term_name, for_update=True)
		old = previous.get(term_name)
		if not old and term.status != "active":
			fail(f"Only active {kind}s can be assigned to Students.")
		row.assigned_by = old.assigned_by if old else frappe.session.user
		row.assigned_at = old.assigned_at if old else frappe.utils.now_datetime()
		row.source = old.source if old else "manual"


def validate_classifications(doc):
	_validate_level(doc, "potential")
	_validate_level(doc, "intent")
	_validate_assignments(doc, "needs", "CRM Need", "need", "Need")
	_validate_assignments(doc, "tags", "CRM Tag", "tag", "Tag")
	# Keep the hidden legacy field valid while old local data is migrated. New
	# callers must use needs/tags and cannot use this field to bypass term status.
	legacy_rows = doc.get("classifications", [])
	if len(legacy_rows) > 100:
		fail("Legacy Student classifications cannot contain more than 100 terms.")
	before = doc.get_doc_before_save()
	previous_legacy = {row.term: row for row in (before.get("classifications", []) if before else [])}
	for row in legacy_rows:
		term = frappe.get_doc("CRM Classification Term", row.term, for_update=True)
		if row.term not in previous_legacy and term.status != "active":
			fail("Only active legacy terms can be assigned to Students.")
		old = previous_legacy.get(row.term)
		row.kind = term.kind
		row.assigned_by = old.assigned_by if old else frappe.session.user
		row.assigned_at = old.assigned_at if old else frappe.utils.now_datetime()
		row.source = old.source if old else "legacy"
