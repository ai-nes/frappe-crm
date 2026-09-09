"""Remove legacy Lead/Student status projections after migrating their values.

``processing_status``/``resolution`` are the Lead workflow contract and
``student_stage`` is the Student workflow contract.  The old status columns
were compatibility projections and must not survive a schema migration even
when Frappe's model sync leaves custom columns in place.
"""

from __future__ import annotations

import frappe

REMOVED_FIELDS = {
	"CRM Lead": ("lead_status", "conversion_status", "enrollment_status", "lifecycle_stage"),
	"CRM Student": ("enrollment_status", "lifecycle_stage"),
}


def _columns(doctype: str) -> set[str]:
	if not frappe.db.table_exists(doctype):
		return set()
	return {row[0] for row in frappe.db.sql(f"SHOW COLUMNS FROM `tab{doctype}`")}


def _backfill_student_stage(columns: set[str]) -> None:
	if "student_stage" not in columns:
		return
	if "enrollment_status" in columns:
		frappe.db.sql(
			"""
			UPDATE `tabCRM Student`
			SET student_stage = CASE UPPER(TRIM(enrollment_status))
				WHEN 'PROSPECT' THEN 'Attempting'
				WHEN 'FOLLOW_UP' THEN 'Attempting'
				WHEN 'CONFIRMED' THEN 'Qualified'
				WHEN 'ENROLLED' THEN 'Connected'
				WHEN 'CONVERTED' THEN 'Connected'
				WHEN 'REFUSED' THEN 'Disqualified'
				ELSE student_stage
			END
			WHERE (student_stage IS NULL OR student_stage = '' OR student_stage = 'New')
			  AND enrollment_status IS NOT NULL
			  AND TRIM(enrollment_status) <> ''
			"""
		)
	if "lifecycle_stage" in columns:
		conditions = ""
		if "enrollment_status" in columns:
			conditions = "AND (enrollment_status IS NULL OR TRIM(enrollment_status) = '')"
		frappe.db.sql(
			f"""
			UPDATE `tabCRM Student`
			SET student_stage = CASE lifecycle_stage
				WHEN 'MQL' THEN 'Attempting'
				WHEN 'Applicant' THEN 'Qualified'
				WHEN 'Enrolled' THEN 'Connected'
				WHEN 'Lost' THEN 'Disqualified'
				ELSE student_stage
			END
			WHERE (student_stage IS NULL OR student_stage = '' OR student_stage = 'New')
			  {conditions}
			  AND lifecycle_stage IS NOT NULL
			  AND TRIM(lifecycle_stage) <> ''
			"""
		)


def _backfill_lead_processing(columns: set[str]) -> None:
	if "processing_status" not in columns:
		return
	if "lead_status" in columns:
		frappe.db.sql(
			"""
			UPDATE `tabCRM Lead`
			SET processing_status = CASE UPPER(TRIM(lead_status))
				WHEN 'WORKING' THEN 'PROCESSING'
				WHEN 'CONTACTED' THEN 'PROCESSING'
				WHEN 'NURTURING' THEN 'PROCESSING'
				WHEN 'QUALIFIED' THEN 'PROCESSED'
				WHEN 'CONVERTED' THEN 'CLOSED'
				WHEN 'UNQUALIFIED' THEN 'CLOSED'
				WHEN 'LOST' THEN 'CLOSED'
				ELSE processing_status
			END
			WHERE (processing_status IS NULL OR processing_status = '' OR processing_status = 'NEW')
			  AND lead_status IS NOT NULL
				AND TRIM(lead_status) <> ''
			"""
		)
		if "resolution" in columns:
			frappe.db.sql(
				"""
				UPDATE `tabCRM Lead`
				SET resolution = CASE UPPER(TRIM(lead_status))
					WHEN 'CONVERTED' THEN 'CREATED'
					WHEN 'UNQUALIFIED' THEN 'INVALID'
					WHEN 'LOST' THEN 'INVALID'
					ELSE resolution
				END
				WHERE (resolution IS NULL OR resolution = '' OR resolution = 'PENDING')
				  AND lead_status IS NOT NULL
				  AND TRIM(lead_status) <> ''
				"""
			)
	if "resolution" in columns and "conversion_status" in columns:
		frappe.db.sql(
			"""
			UPDATE `tabCRM Lead`
			SET resolution = CASE UPPER(TRIM(conversion_status))
				WHEN 'CONVERTED' THEN 'CREATED'
				WHEN 'BLOCKED' THEN 'INVALID'
				ELSE resolution
			END
			WHERE (resolution IS NULL OR resolution = '' OR resolution = 'PENDING')
			  AND conversion_status IS NOT NULL
			  AND TRIM(conversion_status) <> ''
			"""
		)
	if "enrollment_status" in columns:
		frappe.db.sql(
			"""
			UPDATE `tabCRM Lead`
			SET processing_status = CASE UPPER(TRIM(enrollment_status))
				WHEN 'NEW' THEN 'NEW'
				WHEN 'PROSPECT' THEN 'PROCESSING'
				WHEN 'FOLLOW_UP' THEN 'PROCESSING'
				WHEN 'CONFIRMED' THEN 'PROCESSED'
				WHEN 'ENROLLED' THEN 'CLOSED'
				WHEN 'CONVERTED' THEN 'CLOSED'
				WHEN 'REFUSED' THEN 'CLOSED'
				WHEN 'LOST' THEN 'CLOSED'
				ELSE processing_status
			END
			WHERE (processing_status IS NULL OR processing_status = '' OR processing_status = 'NEW')
			  AND enrollment_status IS NOT NULL
			  AND TRIM(enrollment_status) <> ''
			"""
		)
		if "resolution" in columns:
			frappe.db.sql(
				"""
				UPDATE `tabCRM Lead`
				SET resolution = CASE UPPER(TRIM(enrollment_status))
					WHEN 'ENROLLED' THEN 'CREATED'
					WHEN 'CONVERTED' THEN 'CREATED'
					WHEN 'REFUSED' THEN 'INVALID'
					WHEN 'LOST' THEN 'INVALID'
					ELSE resolution
				END
				WHERE (resolution IS NULL OR resolution = '' OR resolution = 'PENDING')
				  AND enrollment_status IS NOT NULL
				  AND TRIM(enrollment_status) <> ''
				"""
			)
	if "lifecycle_stage" in columns:
		frappe.db.sql(
			"""
			UPDATE `tabCRM Lead`
			SET processing_status = CASE lifecycle_stage
				WHEN 'Lead' THEN 'NEW'
				WHEN 'MQL' THEN 'PROCESSING'
				WHEN 'Applicant' THEN 'PROCESSED'
				WHEN 'Enrolled' THEN 'CLOSED'
				WHEN 'Lost' THEN 'CLOSED'
				ELSE processing_status
			END
			WHERE (processing_status IS NULL OR processing_status = '' OR processing_status = 'NEW')
			  AND lifecycle_stage IS NOT NULL
			  AND TRIM(lifecycle_stage) <> ''
			"""
		)
		if "resolution" in columns:
			frappe.db.sql(
				"""
				UPDATE `tabCRM Lead`
				SET resolution = CASE lifecycle_stage
					WHEN 'Enrolled' THEN 'CREATED'
					WHEN 'Lost' THEN 'INVALID'
					ELSE resolution
				END
				WHERE (resolution IS NULL OR resolution = '' OR resolution = 'PENDING')
				  AND lifecycle_stage IS NOT NULL
				  AND TRIM(lifecycle_stage) <> ''
				"""
			)


def _without_removed_fields(value, removed: set[str]):
	if isinstance(value, dict):
		return {key: _without_removed_fields(item, removed) for key, item in value.items()}
	if isinstance(value, list):
		return [
			_without_removed_fields(item, removed)
			for item in value
			if not (isinstance(item, str) and item in removed)
		]
	return value


def _remove_legacy_layout_fields() -> None:
	if not frappe.db.table_exists("Fields Layout"):
		return
	for row in frappe.db.get_all("Fields Layout", fields=["name", "dt", "layout"], limit_page_length=0):
		removed = set(REMOVED_FIELDS.get(row.get("dt"), ()))
		if not removed:
			continue
		if not row.get("layout"):
			continue
		try:
			layout = frappe.parse_json(row.layout)
		except (TypeError, ValueError):
			continue
		cleaned = _without_removed_fields(layout, removed)
		if cleaned != layout:
			frappe.db.set_value(
				"Fields Layout",
				row.name,
				"layout",
				frappe.as_json(cleaned),
				update_modified=False,
			)


def execute() -> None:
	student_columns = _columns("CRM Student")
	lead_columns = _columns("CRM Lead")
	_backfill_student_stage(student_columns)
	_backfill_lead_processing(lead_columns)

	for doctype, fields in REMOVED_FIELDS.items():
		columns = _columns(doctype)
		for fieldname in fields:
			if fieldname in columns:
				frappe.db.sql_ddl(f"ALTER TABLE `tab{doctype}` DROP COLUMN `{fieldname}`")
		frappe.clear_cache(doctype=doctype)
	_remove_legacy_layout_fields()
