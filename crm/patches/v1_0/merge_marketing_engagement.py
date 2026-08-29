"""Migrate attribution evidence and drop the two superseded DocTypes."""

from __future__ import annotations

import frappe

TARGET = "CRM Marketing Engagement"


def _copy(doctype: str, kind: str, reference_doctype: str, fields: list[str]) -> int:
	if not frappe.db.exists("DocType", doctype):
		return 0
	rows = frappe.get_all(doctype, fields=["name", "creation", "modified", "owner", "modified_by", *fields], order_by="creation asc")
	invalid = [row.name for row in rows if not row.get("student")]
	if invalid:
		frappe.throw(f"Marketing engagement migration found rows without a Student: {', '.join(invalid[:20])}")
	created = 0
	previous = getattr(frappe.flags, "student_attribution_migration", False)
	frappe.flags.student_attribution_migration = True
	try:
		for row in rows:
			if frappe.db.exists(TARGET, row.name):
				continue
			values = {
				"doctype": TARGET,
				"name": row.name,
				"engagement_kind": kind,
				"reference_doctype": reference_doctype,
				"reference_name": row.get("crm_campaign") or row.get("crm_event"),
			}
			values.update({field: row.get(field) for field in fields})
			# db_insert avoids live append-only/interaction hooks and preserves the
			# historical row as a migration, not as new present-day activity.
			frappe.get_doc(values).db_insert(ignore_if_duplicate=True)
			frappe.db.sql(
				"""update `tabCRM Marketing Engagement`
				set creation=%s, modified=%s, owner=%s, modified_by=%s
				where name=%s""",
				(row.creation, row.modified, row.owner, row.modified_by, row.name),
			)
			created += 1
	finally:
		frappe.flags.student_attribution_migration = previous
	return created


def execute():
	"""Migrate both legacy evidence tables exactly once and verify totals."""
	before = {
		"campaign": frappe.db.count("CRM Campaign Touchpoint") if frappe.db.exists("DocType", "CRM Campaign Touchpoint") else 0,
		"event": frappe.db.count("CRM Event Participation") if frappe.db.exists("DocType", "CRM Event Participation") else 0,
	}
	if not frappe.db.exists("DocType", TARGET):
		frappe.throw(f"{TARGET} DocType is missing; run model sync before this patch")
	target_before = {
		"campaign_touch": frappe.db.count(TARGET, {"engagement_kind": "campaign_touch"}),
		"event_participation": frappe.db.count(TARGET, {"engagement_kind": "event_participation"}),
	}
	source_rows = {
		"campaign_touch": frappe.get_all("CRM Campaign Touchpoint", fields=["name"]) if before["campaign"] else [],
		"event_participation": frappe.get_all("CRM Event Participation", fields=["name"]) if before["event"] else [],
	}
	already_present = {
		kind: {row.name for row in rows if frappe.db.exists(TARGET, row.name)} for kind, rows in source_rows.items()
	}
	_copy(
		"CRM Campaign Touchpoint",
		"campaign_touch",
		"CRM Campaign",
		["crm_campaign", "crm_contact", "student", "command_receipt", "idempotency_key", "correlation_id", "supersedes", "touched_at", "source", "crm_segment", "notes"],
	)
	_copy(
		"CRM Event Participation",
		"event_participation",
		"CRM Event",
		["crm_event", "crm_contact", "student", "command_receipt", "idempotency_key", "correlation_id", "supersedes", "status", "actor", "registered_at", "checked_in_at", "feedback_rating", "feedback_notes"],
	)
	for source, kind, reference, reference_field in (
		("CRM Campaign Touchpoint", "campaign_touch", "CRM Campaign", "crm_campaign"),
		("CRM Event Participation", "event_participation", "CRM Event", "crm_event"),
	):
		if frappe.db.exists("DocType", source):
			for row in frappe.get_all(source, fields=["name", reference_field]):
				if not frappe.db.exists(TARGET, {"name": row.name, "engagement_kind": kind, "reference_doctype": reference}):
					frappe.throw(f"Marketing engagement migration lost {source} row {row.name}")
	for fields, index_name in (
		(["student", "engagement_kind", "crm_campaign", "touched_at"], "crm_marketing_engagement_campaign_idx"),
		(["student", "engagement_kind", "crm_event", "registered_at"], "crm_marketing_engagement_event_idx"),
	):
		if not frappe.db.sql("SHOW INDEX FROM `tabCRM Marketing Engagement` WHERE Key_name = %s", index_name):
			frappe.db.add_index(TARGET, fields, index_name)
	target_after = {
		"campaign_touch": frappe.db.count(TARGET, {"engagement_kind": "campaign_touch"}),
		"event_participation": frappe.db.count(TARGET, {"engagement_kind": "event_participation"}),
	}
	for kind in target_before:
		expected = target_before[kind] + len(source_rows[kind]) - len(already_present[kind])
		if target_after[kind] != expected:
			frappe.throw(f"Marketing engagement migration count mismatch for {kind}: expected {expected}, found {target_after[kind]}")
	frappe.db.sql(
		"""update `tabCRM Interaction`
		set reference_doctype=%s
		where reference_doctype in (%s, %s)""",
		(TARGET, "CRM Campaign Touchpoint", "CRM Event Participation"),
	)
	for source in ("CRM Campaign Touchpoint", "CRM Event Participation"):
		if frappe.db.exists("DocType", source):
			frappe.delete_doc("DocType", source, ignore_permissions=True, force=True)
		table = f"tab{source}"
		if frappe.db.sql("SHOW TABLES LIKE %s", (table,)):
			frappe.db.sql_ddl(f"DROP TABLE `{table}`")
	after = frappe.db.count(TARGET)
	expected = before["campaign"] + before["event"]
	expected_total = target_before["campaign_touch"] + target_before["event_participation"] + expected - sum(len(names) for names in already_present.values())
	if after != expected_total:
		frappe.throw(f"Marketing engagement total mismatch: expected {expected_total}, found {after}")
	return {"before": before, "migrated": expected, "after": after, "dropped": ["CRM Campaign Touchpoint", "CRM Event Participation"]}
