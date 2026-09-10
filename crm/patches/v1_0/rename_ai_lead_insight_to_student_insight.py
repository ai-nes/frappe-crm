"""Rename the AI insight DocTypes to the Student-first names."""

from __future__ import annotations

import frappe
from frappe.model.rename_doc import rename_doc

RENAMES = (
	("CRM AI Lead Insight Item", "CRM AI Student Insight Item"),
	("CRM AI Lead Insight", "CRM AI Student Insight"),
)


def _table_columns(doctype: str) -> list[str]:
	return [row["Field"] for row in frappe.db.sql(f"SHOW COLUMNS FROM `tab{doctype}`", as_dict=True)]


def _copy_rows(old: str, new: str) -> None:
	"""Copy legacy rows when model sync created the new table before this patch."""
	if not frappe.db.table_exists(old) or not frappe.db.table_exists(new):
		return
	old_columns = set(_table_columns(old))
	new_columns = _table_columns(new)
	columns = [column for column in new_columns if column in old_columns]
	if "name" not in columns:
		return

	insert_columns = ", ".join(f"`{column}`" for column in columns)
	select_columns = ", ".join(f"old_row.`{column}`" for column in columns)
	frappe.db.sql(
		f"""
		INSERT INTO `tab{new}` ({insert_columns})
		SELECT {select_columns}
		FROM `tab{old}` old_row
		LEFT JOIN `tab{new}` new_row ON new_row.name = old_row.name
		WHERE new_row.name IS NULL
		"""
	)


def _copy_child_rows(old: str, new: str) -> None:
	"""Copy child rows and update their parenttype to the renamed parent DocType."""
	if not frappe.db.table_exists(old) or not frappe.db.table_exists(new):
		return
	old_columns = set(_table_columns(old))
	new_columns = _table_columns(new)
	columns = [column for column in new_columns if column in old_columns]
	if "name" not in columns:
		return

	insert_columns = ", ".join(f"`{column}`" for column in columns)
	select_columns = ", ".join(
		"'CRM AI Student Insight'" if column == "parenttype" else f"old_row.`{column}`"
		for column in columns
	)
	frappe.db.sql(
		f"""
		INSERT INTO `tab{new}` ({insert_columns})
		SELECT {select_columns}
		FROM `tab{old}` old_row
		LEFT JOIN `tab{new}` new_row ON new_row.name = old_row.name
		WHERE new_row.name IS NULL
		"""
	)


def _merge_existing_doctype(old: str, new: str) -> None:
	if old.endswith(" Item"):
		_copy_child_rows(old, new)
	else:
		_copy_rows(old, new)
	frappe.delete_doc("DocType", old, force=True, ignore_permissions=True)
	_drop_legacy_table(old, new)


def _drop_legacy_table(old: str, new: str) -> None:
	if not frappe.db.table_exists(old):
		return
	if not frappe.db.table_exists(new):
		raise frappe.ValidationError(f"Cannot remove {old}: target table {new} does not exist.")
	missing_rows = frappe.db.sql(
		f"""
		SELECT old_row.name
		FROM `tab{old}` old_row
		LEFT JOIN `tab{new}` new_row ON new_row.name = old_row.name
		WHERE new_row.name IS NULL
		LIMIT 1
		"""
	)
	if missing_rows:
		raise frappe.ValidationError(
			f"Cannot remove {old}: at least one legacy row was not copied to {new}."
		)
	frappe.db.sql_ddl(f"DROP TABLE `tab{old}`")


def execute():
	frappe.flags.ignore_route_conflict_validation = True

	try:
		for old, new in RENAMES:
			if not frappe.db.exists("DocType", old):
				continue
			if frappe.db.exists("DocType", new):
				_merge_existing_doctype(old, new)
			else:
				rename_doc(
					"DocType",
					old,
					new,
					force=True,
					ignore_permissions=True,
					show_alert=False,
					rebuild_search=False,
				)
				frappe.reload_doctype(new, force=True)
				if old.endswith(" Item"):
					_copy_child_rows(old, new)
				else:
					_copy_rows(old, new)
				_drop_legacy_table(old, new)
			frappe.reload_doctype(new, force=True)
	finally:
		frappe.flags.ignore_route_conflict_validation = False

	frappe.clear_cache()
