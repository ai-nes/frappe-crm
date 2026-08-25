"""Prepare Phase 6 indexes and fenced outbox delivery without rewriting history."""

from __future__ import annotations

import frappe


def _columns(doctype: str) -> set[str]:
	try:
		return {field.fieldname for field in frappe.get_meta(doctype).fields}
	except Exception:
		return set()


def _add_index(doctype: str, fields: tuple[str, ...], name: str, unique: bool = False) -> bool:
	if not frappe.db.table_exists(doctype) or not set(fields) <= _columns(doctype):
		return False
	table = f"tab{doctype}"
	if frappe.db.sql(f"SHOW INDEX FROM `{table}` WHERE Key_name = %s", name):
		return True
	columns = ", ".join(f"`{field}`" for field in fields)
	if unique:
		duplicates = frappe.db.sql(
			f"SELECT {columns}, COUNT(*) AS row_count FROM `{table}` GROUP BY {columns} HAVING row_count > 1 LIMIT 1",
			as_dict=True,
		)
		if duplicates:
			frappe.log_error(
				f"Phase 6 skipped {name}; duplicate rows require quarantine",
				"phase6_prepare_student_decisions",
			)
			return False
	frappe.db.sql_ddl(
		f"ALTER TABLE `{table}` ADD {'UNIQUE ' if unique else ''}INDEX `{name}` ({columns})"
	)
	return True


def execute():
	indexes = (
		("CRM Sales Action", ("recommendation",), "crm_sales_action_recommendation_uniq", True),
		("CRM Sales Action", ("assignee_staff", "execution_status", "due_at"), "crm_sales_action_queue_idx", False),
		("CRM Sales Action", ("student", "action_revision", "name"), "crm_sales_action_student_revision_idx", False),
		("CRM Student Decision Event", ("student", "occurred_at", "name"), "crm_student_decision_event_student_at_idx", False),
		("CRM Student Decision Event", ("idempotency_key",), "crm_student_decision_event_idempotency_idx", False),
		("CRM Agent Event", ("status", "lease_expires_at", "next_attempt_at"), "crm_agent_event_delivery_idx", False),
	)
	ready, skipped = [], []
	for doctype, fields, name, unique in indexes:
		(skipped if not _add_index(doctype, fields, name, unique) else ready).append(name)
	return {"indexes_ready": ready, "indexes_skipped": skipped, "legacy_repaired": 0}
