"""Merge context and scoring revision journals into one two-stream journal."""

from __future__ import annotations

import hashlib

import frappe


TARGET = "CRM Student Revision Journal"
SOURCES = (("CRM Student Context Change", "context_changed", "context"), ("CRM Score Input Change", "score_input_changed", "scoring"))


def _checksum(rows):
	body = "|".join(f"{row.name}:{row.student}:{row.global_sequence}:{row.revision}" for row in rows)
	return hashlib.sha256(body.encode()).hexdigest()


def execute():
	if not frappe.db.exists("DocType", TARGET):
		frappe.throw(f"{TARGET} DocType is missing; run model sync before this patch")
	before = {}
	for source, event_type, stream in SOURCES:
		rows = frappe.get_all(source, fields=["name", "student", "revision", "global_sequence", "reason", "event_id", "occurred_at", "creation", "modified", "owner", "modified_by"], order_by="global_sequence asc, name asc") if frappe.db.exists("DocType", source) else []
		before[stream] = {"count": len(rows), "checksum": _checksum(rows), "rows": rows}
		for row in rows:
			if frappe.db.exists(TARGET, row.name):
				continue
			frappe.get_doc({
				"doctype": TARGET, "name": row.name, "event_id": row.event_id or row.name,
				"student": row.student, "event_type": event_type, "stream": stream,
				"revision": row.revision, "stream_sequence": row.global_sequence,
				"reason": row.reason, "actor": row.owner or "Administrator",
				"actor_scope": {"source": source}, "occurred_at": row.occurred_at,
				"idempotency_key": f"{stream}:{row.event_id or row.name}", "correlation_id": row.event_id or row.name,
				"policy_version": "revision-journal-migration-v1", "schema_version": "revision-journal-v1",
				"payload": {"legacy_doctype": source, "legacy_name": row.name, "revision": row.revision},
				"creation": row.creation, "modified": row.modified, "owner": row.owner, "modified_by": row.modified_by,
			}).db_insert(ignore_if_duplicate=True)
		for row in rows:
			if not frappe.db.exists(TARGET, {"name": row.name, "event_type": event_type, "stream": stream, "stream_sequence": row.global_sequence}):
				frappe.throw(f"Revision journal migration lost {source} row {row.name}")
		if rows:
			max_sequence = max(int(row.global_sequence or 0) for row in rows)
			frappe.db.sql("INSERT IGNORE INTO `tabCRM Event Stream Cursor` (name, stream, counter, creation, modified, owner, modified_by) VALUES (%s, %s, %s, NOW(), NOW(), %s, %s)", (stream, stream, max_sequence, frappe.session.user, frappe.session.user))
			frappe.db.sql("UPDATE `tabCRM Event Stream Cursor` SET counter=GREATEST(counter,%s) WHERE stream=%s", (max_sequence, stream))
	after = {}
	for source, event_type, stream in SOURCES:
		rows = frappe.get_all(TARGET, filters={"stream": stream, "event_type": event_type}, fields=["name", "student", "revision", "stream_sequence"], order_by="stream_sequence asc, name asc")
		after[stream] = len(rows)
		if len(rows) != before[stream]["count"]:
			frappe.throw(f"Revision journal count mismatch for {stream}: expected {before[stream]['count']}, found {len(rows)}")
	for source, _, _ in SOURCES:
		if frappe.db.exists("DocType", source):
			frappe.delete_doc("DocType", source, ignore_permissions=True, force=True)
		table = f"tab{source}"
		if frappe.db.sql("SHOW TABLES LIKE %s", (table,)):
			frappe.db.sql_ddl(f"DROP TABLE `{table}`")
	return {"before": {stream: data["count"] for stream, data in before.items()}, "after": after, "dropped": [source for source, _, _ in SOURCES]}
