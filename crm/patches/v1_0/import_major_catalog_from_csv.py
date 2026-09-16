"""Import the Major Group → Major catalog from the maintained CSV source."""

from __future__ import annotations

import csv
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

import frappe

MAJOR_GROUP = "CRM Major Group"
MAJOR = "CRM Major"
CSV_FILENAME = "Ngành_học (5).csv"


def _default_csv_path() -> Path:
	app_path = Path(frappe.get_app_path("crm")).resolve()
	candidates = (
		app_path.joinpath("..", "..", "docs", CSV_FILENAME),
		app_path.joinpath("..", "..", "..", "docs", CSV_FILENAME),
		Path("/workspace/docs", CSV_FILENAME),
	)
	return next(
		(candidate.resolve() for candidate in candidates if candidate.exists()), candidates[0].resolve()
	)


def _group_code(label: str) -> str:
	value = label.replace("Đ", "D").replace("đ", "d")
	value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
	value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()
	return value[:50] or "UNSPECIFIED"


def _clean(value: Any) -> str:
	return str(value or "").strip()


def _existing_groups() -> tuple[dict[str, Any], dict[str, Any]]:
	rows = frappe.get_all(
		MAJOR_GROUP,
		fields=["name", "code", "display_name", "enabled", "sort_order"],
		limit_page_length=0,
	)
	by_code = {str(row.code).casefold(): row for row in rows if row.code}
	by_name = {str(row.display_name).casefold(): row for row in rows if row.display_name}
	return by_code, by_name


def _existing_majors() -> dict[str, Any]:
	rows = frappe.get_all(MAJOR, fields=["name", "major_name"], limit_page_length=0)
	return {str(row.major_name).casefold(): row for row in rows if row.major_name}


def import_major_catalog(csv_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
	"""Import catalog rows idempotently and return a migration-friendly summary."""
	path = Path(csv_path).expanduser() if csv_path else _default_csv_path()
	if not path.exists():
		message = f"Major catalog CSV not found: {path}"
		frappe.log_error(message, "Major catalog import")
		return {
			"path": str(path),
			"created": {"groups": 0, "majors": 0},
			"updated": {"groups": 0, "majors": 0},
			"skipped": 0,
			"errors": [message],
		}

	group_by_code, group_by_name = _existing_groups()
	major_by_name = _existing_majors()
	created = {"groups": 0, "majors": 0}
	updated = {"groups": 0, "majors": 0}
	errors: list[str] = []
	seen_groups: set[str] = set()
	rows: list[dict[str, str]] = []

	with path.open(encoding="utf-8-sig", newline="") as source:
		for row in csv.DictReader(source):
			rows.append({key: _clean(value) for key, value in row.items() if key})

	for row_number, row in enumerate(rows, start=2):
		major_name = _clean(row.get("Tên ngành"))
		major_code = _clean(row.get("Mã ngành"))
		group_name = _clean(row.get("Nhóm ngành"))
		if not major_name:
			errors.append(f"Row {row_number}: missing major name")
			continue
		if not major_code:
			errors.append(f"Row {row_number}: missing major code for {major_name}")
			continue

		group_id = None
		if group_name:
			group_key = group_name.casefold()
			is_first_group_row = group_key not in seen_groups
			code = _group_code(group_name)
			group = group_by_code.get(code.casefold()) or group_by_name.get(group_key)
			if group is None:
				group = frappe.get_doc(
					{
						"doctype": MAJOR_GROUP,
						"code": code,
						"display_name": group_name,
						"enabled": 1,
						"sort_order": len(seen_groups),
					}
				).insert(ignore_permissions=True)
				group_by_code[code.casefold()] = group
				group_by_name[group_key] = group
				created["groups"] += 1
			elif is_first_group_row:
				group = frappe.get_doc(MAJOR_GROUP, group.name)
				values = {}
				if group.display_name != group_name:
					values["display_name"] = group_name
				if group.sort_order != len(seen_groups):
					values["sort_order"] = len(seen_groups)
				if values:
					for fieldname, value in values.items():
						group.set(fieldname, value)
					group.save(ignore_permissions=True)
					updated["groups"] += 1
				group_by_name[group_key] = group
			group_id = group.name
			seen_groups.add(group_key)

		major = major_by_name.get(major_name.casefold())
		if major is None:
			major = frappe.get_doc(
				{
					"doctype": MAJOR,
					"major_name": major_name,
					"major_code": major_code,
					"major_group": group_id,
					"is_active": 1,
				}
			).insert(ignore_permissions=True)
			major_by_name[major_name.casefold()] = major
			created["majors"] += 1
			continue

		major = frappe.get_doc(MAJOR, major.name)
		values = {}
		if major.major_code != major_code:
			values["major_code"] = major_code
		if major.major_group != group_id:
			values["major_group"] = group_id
		if not major.is_active:
			values["is_active"] = 1
		if values:
			for fieldname, value in values.items():
				major.set(fieldname, value)
			major.save(ignore_permissions=True)
			updated["majors"] += 1

	frappe.db.commit()
	result = {
		"path": str(path),
		"rows": len(rows),
		"created": created,
		"updated": updated,
		"skipped": len(errors),
		"errors": errors,
	}
	print(f"Major catalog import done: {result}")
	return result


def execute() -> dict[str, Any]:
	return import_major_catalog()
