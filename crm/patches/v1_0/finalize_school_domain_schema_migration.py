"""Validate School-domain cutover on sites that already ran the first patch."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import frappe


def _path() -> Path:
	return Path(frappe.get_site_path("private", "backups", "school-domain-schema-final-report.json"))


def _ids(query: str) -> list[str]:
	return [row[0] for row in frappe.db.sql(query)]


def _backup_available() -> bool:
	backup_dir = _path().parent
	return any(backup_dir.glob("*database*.sql.gz"))


def _meta_field_present(doctype: str, fieldname: str) -> bool:
	return bool(frappe.get_meta(doctype).has_field(fieldname))


def execute():
	orphan_activity_ids = _ids(
		"select activity.name from `tabCRM School Activity` activity "
		"left join `tabCRM School Stakeholder` association "
		"on association.name = activity.stakeholder "
		"where activity.stakeholder is not null and activity.stakeholder != '' "
		"and association.name is null"
	)
	duplicate_association_ids = _ids(
		"select group_concat(name) from `tabCRM School Stakeholder` "
		"group by high_school, person having count(*) > 1"
	)
	duplicate_snapshot_ids = _ids(
		"select group_concat(name) from `tabCRM High School Annual Snapshot` "
		"group by high_school, admission_year having count(*) > 1"
	)
	report = {
		"version": 1,
		"kind": "school-domain-schema-final-report",
		"completed_at": datetime.now(timezone.utc).isoformat(),
		"backup_available": _backup_available(),
		"association_count": frappe.db.count("CRM School Stakeholder"),
		"activity_count": frappe.db.count("CRM School Activity"),
		"orphan_activity_ids": orphan_activity_ids,
		"duplicate_association_groups": duplicate_association_ids,
		"duplicate_snapshot_groups": duplicate_snapshot_ids,
		"retired_fields_present_in_metadata": {
			"CRM High School.source_identity": _meta_field_present("CRM High School", "source_identity"),
			"CRM Person.high_school": _meta_field_present("CRM Person", "high_school"),
			"CRM School Activity.ne_output": _meta_field_present("CRM School Activity", "ne_output"),
		},
		"legacy_columns_retained_for_backup_rollback": {
			"CRM High School.source_identity": frappe.db.has_column("CRM High School", "source_identity"),
			"CRM Person.high_school": frappe.db.has_column("CRM Person", "high_school"),
			"CRM School Activity.ne_output": frappe.db.has_column("CRM School Activity", "ne_output"),
		},
	}
	_path().parent.mkdir(parents=True, exist_ok=True)
	_path().write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
	if orphan_activity_ids or duplicate_association_ids or duplicate_snapshot_ids:
		frappe.throw(
			"School-domain cutover validation found orphan or duplicate records; see final report.",
			frappe.ValidationError,
		)
