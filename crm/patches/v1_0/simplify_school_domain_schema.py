"""Backfill the normalized School domain before legacy fields are retired.

The protected backup is intentionally separate from School-domain records. It
contains only the legacy relationship values needed for rollback; the public
report contains counts and record IDs, never contact details or source rows.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import frappe

SNAPSHOT_VERSION = 1


def _table_exists(doctype: str) -> bool:
	return bool(frappe.db.table_exists(doctype))


def _column_exists(doctype: str, fieldname: str) -> bool:
	return bool(_table_exists(doctype) and frappe.db.has_column(doctype, fieldname))


def _backup_path(kind: str) -> Path:
	return Path(frappe.get_site_path("private", "backups", f"school-domain-schema-v{SNAPSHOT_VERSION}-{kind}.json"))


def _write_json(path: Path, payload: dict) -> str:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
	return str(path)


def _legacy_rows(doctype: str, fields: list[str], where: str) -> list[dict]:
	available = [field for field in fields if _column_exists(doctype, field)]
	if not available or not _table_exists(doctype):
		return []
	return frappe.db.sql(
		"select " + ", ".join(f"`{field}`" for field in available)
		+ f" from `tab{doctype}` where {where}",
		as_dict=True,
	)


def _capture_snapshot() -> dict:
	person_relationships = (
		_legacy_rows(
			"CRM Person",
			[
				"name", "full_name", "role", "stakeholder_role", "high_school",
				"relationship_status", "influence", "owner_staff", "owning_team",
			],
			"high_school is not null and high_school != ''",
		)
		if _column_exists("CRM Person", "high_school")
		else []
	)
	activity_stakeholders = (
		_legacy_rows(
			"CRM School Activity",
			["name", "high_school", "stakeholder"],
			"stakeholder is not null and stakeholder != ''",
		)
		if _column_exists("CRM School Activity", "stakeholder")
		else []
	)
	activity_metrics = (
		_legacy_rows(
			"CRM School Activity",
			["name", "application_count", "ne_output"],
			"ne_output is not null and ne_output != ''",
		)
		if _column_exists("CRM School Activity", "ne_output")
		else []
	)
	return {
		"version": SNAPSHOT_VERSION,
		"kind": "school-domain-schema",
		"captured_at": datetime.now(timezone.utc).isoformat(),
		"person_relationships": person_relationships,
		"activity_stakeholders": activity_stakeholders,
		"activity_metrics": activity_metrics,
	}


def _duplicate_record_ids(doctype: str, fields: list[str]) -> list[str]:
	if not _table_exists(doctype) or any(not _column_exists(doctype, field) for field in fields):
		return []
	rows = frappe.db.sql(
		"select name, " + ", ".join(f"`{field}`" for field in fields)
		+ f" from `tab{doctype}`",
		as_dict=True,
	)
	groups = {}
	for row in rows:
		key = tuple(row.get(field) for field in fields)
		if any(value in (None, "") for value in key):
			continue
		groups.setdefault(key, []).append(row.name)
	return sorted(name for names in groups.values() if len(names) > 1 for name in names)


def _missing_key_ids(doctype: str, fields: list[str]) -> list[str]:
	if not _table_exists(doctype) or any(not _column_exists(doctype, field) for field in fields):
		return []
	rows = frappe.db.sql(
		"select name, " + ", ".join(f"`{field}`" for field in fields)
		+ f" from `tab{doctype}`",
		as_dict=True,
	)
	return sorted(
		row.name for row in rows if any(row.get(field) in (None, "") for field in fields)
	)


def _same_metric(left, right) -> bool:
	if left in (None, "") or right in (None, ""):
		return False
	try:
		return float(left) == float(right)
	except (TypeError, ValueError):
		return str(left).strip() == str(right).strip()


def _default_stakeholder_role() -> str | None:
	role = frappe.db.get_value(
		"CRM Term", {"term_name": "Đầu mối tuyển sinh", "category": "stakeholder_role"}, "name"
	)
	if role:
		return role
	previous = getattr(frappe.flags, "crm_governance_additive", False)
	frappe.flags.crm_governance_additive = True
	try:
		return frappe.get_doc(
			{
				"doctype": "CRM Term",
				"term_name": "Đầu mối tuyển sinh",
				"category": "stakeholder_role",
				"is_active": 1,
			}
		).insert(ignore_permissions=True).name
	finally:
		frappe.flags.crm_governance_additive = previous


def _migrate_application_count(report: dict) -> None:
	if not _column_exists("CRM School Activity", "ne_output") or not _column_exists(
		"CRM School Activity", "application_count"
	):
		return
	fields = ["name", "ne_output"]
	fields.append("application_count")
	rows = frappe.db.sql(
		"select " + ", ".join(f"`{field}`" for field in fields)
		+ " from `tabCRM School Activity` where ne_output is not null and ne_output != ''",
		as_dict=True,
	)
	for row in rows:
		if row.get("application_count") in (None, ""):
			frappe.db.set_value(
				"CRM School Activity", row.name, "application_count", row.ne_output, update_modified=False
			)
			report["ne_output_migrated_ids"].append(row.name)
		elif not _same_metric(row.application_count, row.ne_output):
			report["ne_output_conflict_ids"].append(row.name)


def _copy_person_relationships(snapshot: dict, report: dict) -> None:
	if not _table_exists("CRM School Stakeholder"):
		return
	for row in snapshot.get("person_relationships", []):
		role = row.get("stakeholder_role")
		if not role and row.get("role"):
			role = frappe.db.get_value(
				"CRM Term", {"term_name": row["role"], "category": "stakeholder_role"}, "name"
			)
		if not role:
			role = _default_stakeholder_role()
		if not role:
			report["unresolved_person_ids"].append(row.get("name"))
			continue
		if frappe.db.exists("CRM School Stakeholder", {"high_school": row.high_school, "person": row.name}):
			report["existing_association_count"] += 1
			continue
		association = frappe.get_doc(
			{
				"doctype": "CRM School Stakeholder",
				"high_school": row.high_school,
				"person": row.name,
				"stakeholder_role": role,
				"position_title": row.get("role"),
				"relationship_status": row.get("relationship_status") or "New",
				"influence": row.get("influence"),
				"owner_staff": row.get("owner_staff"),
				"owning_team": row.get("owning_team"),
			}
		).insert(ignore_permissions=True)
		report["created_association_ids"].append(association.name)


def _migrate_activity_stakeholders(snapshot: dict, report: dict) -> None:
	if not _column_exists("CRM School Activity", "stakeholder"):
		return
	for row in snapshot.get("activity_stakeholders", []):
		current_association = frappe.db.get_value(
			"CRM School Stakeholder", row.stakeholder, ["name", "high_school"], as_dict=True
		)
		if current_association and current_association.high_school == row.high_school:
			# A rerun must leave an already normalized association untouched.
			continue
		association = frappe.db.get_value(
			"CRM School Stakeholder",
			{"high_school": row.high_school, "person": row.stakeholder},
			"name",
		)
		if association:
			frappe.db.set_value("CRM School Activity", row.name, "stakeholder", association, update_modified=False)
			report["rewritten_activity_ids"].append(row.name)
		else:
			# The protected backup retains the unresolved legacy Person ID; clearing
			# the link prevents an orphan Link after the field option is changed.
			frappe.db.set_value("CRM School Activity", row.name, "stakeholder", None, update_modified=False)
			report["unresolved_activity_ids"].append(row.name)


def _report_payload(report: dict, snapshot: dict) -> dict:
	return {
		"version": SNAPSHOT_VERSION,
		"kind": "school-domain-schema-migration-report",
		"completed_at": datetime.now(timezone.utc).isoformat(),
		"before": {
			"person_relationship_count": len(snapshot.get("person_relationships", [])),
			"activity_stakeholder_count": len(snapshot.get("activity_stakeholders", [])),
		},
		"after": {
			"association_count": frappe.db.count("CRM School Stakeholder"),
			"activity_stakeholder_count": frappe.db.count("CRM School Activity", {"stakeholder": ["is", "set"]}),
		},
		"details": report,
		"backup_file": str(_backup_path("backup")),
	}


def rollback_relationship_backfill(snapshot: dict) -> None:
	"""Reverse this patch's relationship writes after explicit approval.

	A full schema rollback still requires restoring the protected site backup and
	re-enabling the legacy DocType fields; this helper is the data-layer rehearsal.
	"""
	if not isinstance(snapshot, dict) or snapshot.get("version") != SNAPSHOT_VERSION:
		raise ValueError("invalid School-domain migration backup")
	migration = snapshot.get("migration") or {}
	for row in snapshot.get("activity_stakeholders", []):
		if row.get("name") and row.get("stakeholder") and _column_exists("CRM School Activity", "stakeholder"):
			frappe.db.set_value(
				"CRM School Activity", row["name"], "stakeholder", row["stakeholder"], update_modified=False
			)
	for row in snapshot.get("activity_metrics", []):
		if row.get("name") and _column_exists("CRM School Activity", "application_count"):
			frappe.db.set_value(
				"CRM School Activity", row["name"], "application_count",
				row.get("application_count"), update_modified=False,
			)
	for association in migration.get("created_association_ids", []):
		if frappe.db.exists("CRM School Stakeholder", association):
			frappe.delete_doc("CRM School Stakeholder", association, ignore_permissions=True, force=True)
	frappe.db.commit()


def execute():
	# This patch is intentionally pre_model_sync: create the new association table
	# while legacy fields are still available, then let schema sync retire them.
	frappe.reload_doc("fcrm", "doctype", "crm_school_stakeholder", force=True)
	if not _table_exists("CRM School Stakeholder"):
		return
	snapshot = _capture_snapshot()
	backup_path = _backup_path("backup")
	_write_json(backup_path, snapshot)
	report = {
		"duplicate_high_school_ids": _duplicate_record_ids(
			"CRM High School", ["province", "ward", "school_code"]
		),
		"missing_high_school_key_ids": _missing_key_ids(
			"CRM High School", ["province", "ward", "school_code"]
		),
		"duplicate_snapshot_ids": _duplicate_record_ids(
			"CRM High School Annual Snapshot", ["high_school", "admission_year"]
		),
		"missing_snapshot_key_ids": _missing_key_ids(
			"CRM High School Annual Snapshot", ["high_school", "admission_year"]
		),
		"existing_association_count": 0,
		"created_association_ids": [],
		"rewritten_activity_ids": [],
		"unresolved_person_ids": [],
		"unresolved_activity_ids": [],
		"ne_output_migrated_ids": [],
		"ne_output_conflict_ids": [],
	}
	if any(
		report[key]
		for key in (
			"duplicate_high_school_ids", "missing_high_school_key_ids",
			"duplicate_snapshot_ids", "missing_snapshot_key_ids",
		)
	):
		_write_json(_backup_path("report"), _report_payload(report, snapshot))
		frappe.throw(
			"School-domain migration stopped: duplicate business keys require manual review. "
			"See the protected migration report.",
			frappe.ValidationError,
		)
	savepoint = "simplify_school_domain_schema"
	frappe.db.savepoint(savepoint)
	try:
		_copy_person_relationships(snapshot, report)
		_migrate_activity_stakeholders(snapshot, report)
		_migrate_application_count(report)
		snapshot["migration"] = report
		_write_json(backup_path, snapshot)
		_write_json(_backup_path("report"), _report_payload(report, snapshot))
		frappe.db.commit()
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise
	return report
