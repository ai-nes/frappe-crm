"""Extract the compact JSON inputs used by the school-domain seed."""

from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

try:
	import frappe  # noqa: F401
except ModuleNotFoundError:
	frappe = types.ModuleType("frappe")
	frappe.throw = lambda message: (_ for _ in ()).throw(RuntimeError(message))
	sys.modules["frappe"] = frappe

from crm.demo import school_domain_import as importer


CANONICAL_FIELDS = (
	"province_code",
	"province_name",
	"ward_code",
	"ward_name",
	"school_code",
	"school_name",
	"school_area",
	"school_type",
	"address",
	"latitude",
	"longitude",
)
TS_FIELDS = (
	"province_code",
	"province_name",
	"ward_code",
	"ward_name",
	"school_code",
	"school_name",
	"school_area",
	"school_type",
	"address",
	"pic",
	"team",
	"stakeholder_name",
	"stakeholder_role",
	"stakeholder_phone",
	"stakeholder_email",
	"ne_2022",
	"ne_2023",
	"ne_2024",
	"ne_2025",
	"adjusted_ne_threshold",
	"target_2026",
	"admission_year",
	"activity_type",
	"activity_date",
	"status",
	"outcome",
)
TS_SHEETS = frozenset({
	importer.PRIMARY_TS_SHEET,
	"KHU VỰC 1",
	"LỊCH CHƯƠNG TRÌNH",
	"LỊCH CÔNG TÁC",
})


def _sha256(path: Path) -> str:
	hasher = hashlib.sha256()
	with path.open("rb") as handle:
		for chunk in iter(lambda: handle.read(1024 * 1024), b""):
			hasher.update(chunk)
	return hasher.hexdigest()


def _compact_values(data: dict, fields: tuple[str, ...]) -> list:
	return [data.get(field) or None for field in fields]


def extract_school_seed(source=importer.DEFAULT_SCHOOL_SEED_XLSX_PATH, destination=None) -> str:
	source = Path(source)
	destination = Path(destination or importer.DEFAULT_SCHOOL_SEED_PATH)
	report = importer.reconcile_school_seed(source)
	payload = {
		"schema": "crm-school-domain-input-v1",
		"kind": "canonical_school_seed",
		"source_file": source.name,
		"source_sha256": _sha256(source),
		"source_sheet": report["source_sheet"],
		"profile": importer.profile_workbook(source),
		"fields": list(CANONICAL_FIELDS),
		"rows": [
			[row["source_row"], _compact_values(row["data"], CANONICAL_FIELDS)]
			for row in report["rows"]
		],
	}
	destination.parent.mkdir(parents=True, exist_ok=True)
	destination.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
	return str(destination)


def extract_ts_workbook(source=importer.DEFAULT_TS_XLSX_PATH, destination=None) -> str:
	source = Path(source)
	destination = Path(destination or importer.DEFAULT_TS_PATH)
	workbook = importer._workbook(source)
	rows = []
	sheets = []
	try:
		for sheet in workbook.worksheets:
			if sheet.title not in TS_SHEETS:
				sheets.append({
					"name": sheet.title,
					"kind": importer._sheet_kind(sheet.title),
					"profile": {"status": "omitted", "rows": sheet.max_row, "columns": sheet.max_column},
					"record_count": 0,
				})
				continue
			records, info = importer._sheet_records(sheet)
			sheets.append({
				"name": sheet.title,
				"kind": importer._sheet_kind(sheet.title),
				"profile": info,
				"record_count": len(records),
			})
			for record in records:
				rows.append([sheet.title, record["source_row"], _compact_values(record["data"], TS_FIELDS)])
	finally:
		workbook.close()
	payload = {
		"schema": "crm-school-domain-input-v1",
		"kind": "ts_school_operations",
		"source_file": source.name,
		"source_sha256": _sha256(source),
		"pic_role": "Promoter",
		"fields": list(TS_FIELDS),
		"sheets": sheets,
		"rows": rows,
	}
	destination.parent.mkdir(parents=True, exist_ok=True)
	destination.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
	return str(destination)


def extract_all() -> dict:
	return {
		"school_seed": extract_school_seed(),
		"ts_workbook": extract_ts_workbook(),
	}


if __name__ == "__main__":
	print(json.dumps(extract_all(), ensure_ascii=False))
