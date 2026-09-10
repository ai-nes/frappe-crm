"""Lifecycle validation shared by Segment APIs and generic Document writes."""

from contextlib import contextmanager

import frappe

from crm.fcrm.segment_rules import bounded_text, fail, validate_filters

TRANSITIONS = {
	"draft": ("active", "archive"),
	"active": ("inactive", "archive"),
	"inactive": ("active", "archive"),
	"archive": (),
}
COMMAND_FLAG = "crm_segment_lifecycle_command"


@contextmanager
def lifecycle_command():
	previous = frappe.flags.get(COMMAND_FLAG)
	frappe.flags[COMMAND_FLAG] = True
	try:
		yield
	finally:
		frappe.flags[COMMAND_FLAG] = previous


def validate_segment(doc):
	before = doc.get_doc_before_save()
	doc.title = bounded_text(doc.title, "title")
	doc.purpose = bounded_text(doc.get("purpose"), "purpose", limit=2000, optional=True)
	doc.segment_type = doc.get("segment_type") or "dynamic"
	doc.status = doc.get("status") or "draft"
	if doc.status not in TRANSITIONS or doc.segment_type not in ("dynamic", "static"):
		fail("Unknown Segment status or type.")
	if doc.get("category") not in (None, "", "admission_stage", "potential", "intent", "need"):
		fail("Unknown Segment business category.")
	doc.responsible_user = doc.get("responsible_user") or doc.owner or frappe.session.user
	if doc.responsible_user == "Guest" or not frappe.db.get_value("User", doc.responsible_user, "enabled"):
		fail("An enabled responsible user is required.")
	command = frappe.flags.get(COMMAND_FLAG)
	if not before:
		if doc.status != "draft" or doc.get("snapshot_at") or doc.get("snapshot_by"):
			fail("New segments must start as draft without a snapshot.")
		doc.revision = 0
	else:
		if before.status == "archive":
			fail("Archived segments are read-only.", "INVALID_TRANSITION")
		if doc.status != before.status:
			if not command:
				fail("Use the Segment transition command.", "FORBIDDEN", permission=True)
			if doc.status not in TRANSITIONS[before.status]:
				fail("This status transition is not allowed.", "INVALID_TRANSITION")
		if before.status != "draft" and doc.segment_type != before.segment_type:
			fail("Segment type cannot change after publication.")
		if any(doc.get(f) != before.get(f) for f in ("snapshot_at", "snapshot_by")) and not command:
			fail("Snapshot metadata is command-only.", "FORBIDDEN", permission=True)
		if before.get("snapshot_at") and doc.filters != before.filters:
			# JSON can round-trip as dict or string; compare normalized rules below.
			if validate_filters(doc.filters) != validate_filters(before.filters):
				fail("Captured static Segment rules are immutable. Create a new Segment instead.")
		doc.revision = int(before.get("revision") or 0) + 1
	if doc.filters:
		doc.filters = validate_filters(doc.filters)
	if doc.status == "active":
		if not doc.get("category"):
			fail("An active Segment requires one of the four business categories.")
		if not doc.purpose:
			fail("An active Segment requires a business purpose.")
		doc.filters = validate_filters(doc.filters)
		if doc.segment_type == "static" and not doc.get("snapshot_at"):
			fail("Static Segment activation requires a captured snapshot.")
