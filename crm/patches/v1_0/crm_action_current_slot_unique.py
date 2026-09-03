"""Enforce one current CRM Action per student at the database.

MariaDB has no partial index, so the invariant "at most one non-terminal Action
occupies a student's current slot" is expressed as a plain
``UNIQUE (student, current_slot)``. Terminal and past rows must carry
``current_slot = NULL`` (NULL never collides); an empty string would.

``ALTER TABLE ... ADD UNIQUE KEY`` is not transactional on MariaDB, so this
patch is written to be idempotent and re-runnable:

1. Normalize every existing violation first (empty-string slots to NULL, then
   the newest non-terminal Action per student kept as the current one and every
   other current row for that student vacated), reporting the count touched.
2. Add the unique key only if it is not already present.

Rollback:
  ``DROP INDEX `crm_action_student_current_slot_uniq` ON `tabCRM Action```
  The pre-patch slot values are not recoverable from this patch; restore them
  from a backup if the normalization must be reverted.
"""

import frappe

from crm.fcrm.doctype.crm_action.crm_action import CRMAction
from crm.patches.v1_0.add_student_next_task_v2 import _ensure_unique_index

_INDEX = "crm_action_student_current_slot_uniq"


def execute():
	if not frappe.db.table_exists("CRM Action"):
		return
	touched = _normalize_current_slots()
	if touched:
		print(f"crm_action_current_slot_unique: normalized {touched} conflicting current-slot rows")
	_ensure_unique_index("CRM Action", _INDEX, ["student", "current_slot"])


def _normalize_current_slots() -> int:
	terminal = tuple(sorted(CRMAction.TERMINAL))
	touched = 0

	# An empty-string slot is not "current" but would collide under the key.
	frappe.db.sql(
		"UPDATE `tabCRM Action` SET current_slot = NULL "
		"WHERE current_slot IS NOT NULL AND current_slot != 'CURRENT'"
	)
	touched += frappe.db.sql("SELECT ROW_COUNT() AS n", as_dict=True)[0].n or 0

	# A terminal Action must never keep the current slot.
	frappe.db.sql(
		"UPDATE `tabCRM Action` SET current_slot = NULL WHERE current_slot = 'CURRENT' AND state IN %(terminal)s",
		{"terminal": terminal},
	)
	touched += frappe.db.sql("SELECT ROW_COUNT() AS n", as_dict=True)[0].n or 0

	duplicate_students = frappe.db.sql(
		"""
		SELECT student FROM `tabCRM Action`
		WHERE current_slot = 'CURRENT'
		GROUP BY student
		HAVING COUNT(*) > 1
		""",
		as_dict=True,
	)
	for row in duplicate_students:
		names = frappe.db.sql(
			"""
			SELECT name FROM `tabCRM Action`
			WHERE student = %(student)s AND current_slot = 'CURRENT'
			ORDER BY modified DESC, creation DESC
			""",
			{"student": row.student},
			pluck="name",
		)
		# Keep the most recently touched Action as the current one; vacate the rest.
		for stale in names[1:]:
			frappe.db.set_value("CRM Action", stale, "current_slot", None, update_modified=False)
			touched += 1

	if not frappe.flags.in_test:
		# Durably land the normalization before the non-transactional ADD UNIQUE KEY.
		frappe.db.commit()
	return touched
