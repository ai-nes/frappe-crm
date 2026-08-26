"""Forward-only schema/index guard for the Task-Recommendation merge.

Task absorbs the fields CRM Student Task used to own (current_slot,
producer_identity, generation_idempotency_key, ...). Mirrors the index
creation add_student_next_task_v2.py did for CRM Student Task -- do not edit
that historical patch, this is its Task-doctype successor.
"""

import frappe


def execute():
	frappe.reload_doc("fcrm", "doctype", "task")
	_ensure_unique_index("Task", "task_current_slot_idx", ["student", "current_slot"])
	_ensure_unique_index(
		"Task",
		"task_idempotency_idx",
		["producer_identity", "student", "generation_idempotency_key"],
	)
	# Covers student_worklist.py's _fetch_page keyset query: filters on
	# current_slot/status, orders by worklist_priority_rank, creation, name.
	_ensure_index(
		"Task",
		"task_worklist_idx",
		["current_slot", "status", "worklist_priority_rank", "creation", "name"],
	)


def _ensure_unique_index(doctype, index_name, fields):
	"""MariaDB-safe idempotent unique index creation."""
	if _index_exists(doctype, index_name):
		return
	columns = ", ".join(f"`{field}`" for field in fields)
	frappe.db.sql(f"ALTER TABLE `tab{doctype}` ADD UNIQUE KEY `{index_name}` ({columns})")


def _ensure_index(doctype, index_name, fields):
	"""MariaDB-safe idempotent (non-unique) index creation."""
	if _index_exists(doctype, index_name):
		return
	columns = ", ".join(f"`{field}`" for field in fields)
	frappe.db.sql(f"ALTER TABLE `tab{doctype}` ADD KEY `{index_name}` ({columns})")


def _index_exists(doctype, index_name):
	return bool(
		frappe.db.sql(
			"SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s LIMIT 1",
			(f"tab{doctype}", index_name),
		)
	)
