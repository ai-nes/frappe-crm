"""Safely anchor legacy attribution evidence to CRM Student.

The patch is additive and rerunnable: it only fills a blank ``student`` from
the already-linked Contact, records anomalies for manual review, and never
creates interactions or changes source timestamps/history.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

try:
	import frappe
except ImportError:  # pragma: no cover - pure preflight tests run outside bench
	frappe = None


EVIDENCE_DOCTYPES = ("CRM Campaign Touchpoint", "CRM Event Participation")
INDEXES = (
	("CRM Campaign Touchpoint", ("student", "touched_at", "name"), "crm_campaign_touchpoint_student_timeline_idx"),
	("CRM Campaign Touchpoint", ("student", "crm_campaign", "name"), "crm_campaign_touchpoint_student_campaign_idx"),
	("CRM Event Participation", ("student", "registered_at", "name"), "crm_event_participation_student_timeline_idx"),
	("CRM Event Participation", ("student", "crm_event", "name"), "crm_event_participation_student_event_idx"),
)


def classify_evidence_row(row, contact_students):
	"""Classify one row without mutating it; used for reviewable preflight."""
	student = row.get("student")
	contact = row.get("crm_contact")
	linked_student = contact_students.get(contact)
	if student:
		return "conflict" if linked_student and linked_student != student else "preserved"
	if not contact:
		return "unresolvable_no_contact"
	if not linked_student:
		return "unresolvable_contact"
	return "backfill"


def build_backfill_report(rows: Iterable[dict], contact_students: dict) -> dict:
	items = []
	for row in rows:
		classification = classify_evidence_row(row, contact_students)
		items.append(
			{
				"doctype": row.get("doctype"),
				"name": row.get("name"),
				"crm_contact": row.get("crm_contact"),
				"existing_student": row.get("student"),
				"resolved_student": contact_students.get(row.get("crm_contact")),
				"classification": classification,
			}
		)
	counts = Counter(item["classification"] for item in items)
	return {
		"rows_checked": len(items),
		"backfillable": counts["backfill"],
		"quarantined": counts["conflict"] + counts["unresolvable_no_contact"] + counts["unresolvable_contact"],
		"classifications": dict(sorted(counts.items())),
		"items": items,
	}


def _rows():
	if frappe is None:
		raise RuntimeError("The Phase 7 migration requires a Frappe bench")
	rows = []
	for doctype in EVIDENCE_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		for row in frappe.db.get_all(doctype, fields=["name", "crm_contact", "student"]):
			row["doctype"] = doctype
			rows.append(row)
	return rows


def _contact_students(rows):
	contacts = sorted({row.crm_contact for row in rows if row.crm_contact})
	if not contacts:
		return {}
	return {
		row.name: row.student
		for row in frappe.db.get_all("CRM Contact", filters={"name": ["in", contacts]}, fields=["name", "student"])
		if row.student
	}


def _columns(doctype):
	return {field.fieldname for field in frappe.get_meta(doctype).fields}


def _duplicate_preflight(doctype, fields):
	"""Run before DDL and retain proof if a schema/data anomaly is found."""
	table = f"tab{doctype}"
	columns = ", ".join(f"`{field}`" for field in fields)
	# ``name`` makes these non-unique lookup indexes safe for repeated exposure;
	# the preflight nevertheless ensures every intended column is queryable.
	return frappe.db.sql(
		f"SELECT {columns}, COUNT(*) AS row_count FROM `{table}` "
		f"GROUP BY {columns} HAVING row_count > 1 LIMIT 1",
		as_dict=True,
	)


def _add_index(doctype, fields, index_name):
	if not frappe.db.table_exists(doctype) or not set(fields) <= _columns(doctype):
		return False, "missing_table_or_columns"
	table = f"tab{doctype}"
	if frappe.db.sql(f"SHOW INDEX FROM `{table}` WHERE Key_name = %s", index_name):
		return True, "already_present"
	duplicates = _duplicate_preflight(doctype, fields)
	if duplicates:
		frappe.log_error(frappe.as_json(duplicates), f"Phase 7 duplicate preflight: {index_name}")
		return False, "duplicate_preflight"
	columns = ", ".join(f"`{field}`" for field in fields)
	frappe.db.sql_ddl(f"ALTER TABLE `{table}` ADD INDEX `{index_name}` ({columns})")
	return True, "created"


def execute():
	rows = _rows()
	contact_students = _contact_students(rows)
	report = build_backfill_report(rows, contact_students)
	updated = []
	quarantine = []
	for item in report["items"]:
		if item["classification"] == "backfill":
			# Direct DB update avoids document hooks and preserves modified/source
			# timestamps.  It is guarded by student IS NULL for restart safety.
			frappe.db.sql(
				f"UPDATE `tab{item['doctype']}` SET `student` = %s "
				"WHERE `name` = %s AND (`student` IS NULL OR `student` = '')",
				(item["resolved_student"], item["name"]),
			)
			updated.append(item["name"])
		elif item["classification"] != "preserved":
			quarantine.append(item)
	if quarantine:
		frappe.log_error(frappe.as_json(quarantine), "Phase 7 Student attribution quarantine")
	indexes_ready, indexes_skipped = [], []
	for doctype, fields, index_name in INDEXES:
		ok, reason = _add_index(doctype, fields, index_name)
		(indexes_ready if ok else indexes_skipped).append({"name": index_name, "reason": reason})
	return {
		**report,
		"updated": updated,
		"quarantine": quarantine,
		"indexes_ready": indexes_ready,
		"indexes_skipped": indexes_skipped,
		"interactions_created": 0,
	}
