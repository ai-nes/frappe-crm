"""Focused contracts for the school-domain workbook adapters.

These tests use small generated workbooks so they do not require operational
workbooks or any Frappe database state.  The production importer is imported
with a minimal Frappe fallback when this repository is tested outside bench.
"""

from __future__ import annotations

import sys
import types
import json
from importlib import import_module
from pathlib import Path

import pytest
from openpyxl import Workbook


def _ensure_frappe_importable():
	try:
		import frappe
	except ModuleNotFoundError:
		frappe = types.ModuleType("frappe")
		frappe.throw = lambda message: (_ for _ in ()).throw(RuntimeError(message))
		sys.modules["frappe"] = frappe


_ensure_frappe_importable()

importer = import_module("crm.demo.school_domain_import")
extractor = import_module("crm.demo.extract_school_domain_json")


SEED_HEADERS = [
	"Mã tỉnh",
	"Tên tỉnh",
	"Mã xã",
	"Tên xã",
	"Mã trường",
	"Tên trường",
	"Địa chỉ",
]


def _write_workbook(path: Path, title: str, headers: list[str], rows: list[list[object]]) -> Path:
	workbook = Workbook()
	sheet = workbook.active
	sheet.title = title
	sheet.append(["Generated fixture"])
	sheet.append(headers)
	for row in rows:
		sheet.append(row)
	workbook.save(path)
	return path


def _seed_row(
	province: str,
	name: str,
	code: str,
	*,
	province_code: str = "01",
	ward_code: str = "011",
	address: str = "1 Main Street",
) -> dict:
	return {
		"source_row": 3,
		"source_sheet": "Seed",
		"data": {
			"province_name": province,
			"province_code": province_code,
			"ward_code": ward_code,
			"ward_name": "Ward",
			"school_code": code,
			"school_name": name,
			"address": address,
		},
		"canonical_province": province,
		"source_identity": f"{province_code}:{ward_code}:{code}",
		"match_status": "ready",
	}


def test_all_canonical_provinces_and_declared_aliases_resolve():
	aliases = importer.PROVINCE_ALIASES

	assert len(aliases) == 7
	for canonical, values in aliases.items():
		for value in {canonical, *values}:
			assert importer.canonical_province_name(value) == canonical


def test_school_seed_reconciliation_counts_review_rows_and_provenance(tmp_path):
	path = _write_workbook(
		tmp_path / "school-seed.xlsx",
		"Canonical schools",
		SEED_HEADERS,
		[
			["01", "TP.HCM", "011", "Ward", "S001", "THPT Nguyễn Du", "1 Main Street"],
			["01", "TP HCM", "011", "Ward", "S002", "Trường Trần Phú", "2 Main Street"],
			["02", "Đồng Nai", "021", "Ward", "S003", "THPT Lê Lợi", "3 Main Street"],
			["01", "TP.HCM", "011", "Ward", "S001", "THPT Nguyễn Du", "1 Main Street"],
			["99", "Unknown Province", "991", "Ward", "S004", "THPT Unresolved", "4 Main Street"],
			["01", "TP.HCM", "011", "Ward", "", "THPT Missing Code", "5 Main Street"],
			[None, None, None, None, None, None, None],
		],
	)

	report = importer.reconcile_school_seed(path)

	assert report["total_rows"] == 6
	assert report["status_counts"] == {"ready": 3, "review_required": 3}
	assert report["canonical_provinces"] == ["TP. Đồng Nai", "Tp. Hồ Chí Minh"]
	assert len(report["review_rows"]) == 3
	assert any("duplicate_composite_identity" in row["reasons"] for row in report["rows"])
	assert all(
		row["source_sheet"] and row["source_row"] and row["match_status"] and row["source_identity"]
		for row in report["rows"]
	)


def test_ts_matching_uses_alias_and_source_code_to_disambiguate_duplicate_names():
	seed_rows = [
		_seed_row("Tp. Hồ Chí Minh", "THPT Nguyễn Du", "S001", ward_code="011", address="1 Main Street"),
		_seed_row("Tp. Hồ Chí Minh", "Trường Nguyễn Du", "S002", ward_code="012", address="2 Main Street"),
	]
	by_name, by_global_name, by_identity = importer._school_index(seed_rows)

	matched = importer._match_school(
		{
			"province_name": "Bình Dương",
			"school_name": "Nguyen Du",
			"school_code": "S002",
			"address": "",
		},
		by_name,
		by_global_name,
		by_identity,
	)
	assert matched[1:4] == ("matched", 0.98, ["name_province_and_source_code"])
	assert matched[0]["source_identity"] == "01:012:S002"

	ambiguous = importer._match_school(
		{"province_name": "TP.HCM", "school_name": "THPT Nguyễn Du", "school_code": "", "address": ""},
		by_name,
		by_global_name,
		by_identity,
	)
	assert ambiguous[0] is None
	assert ambiguous[1] == "ambiguous"
	assert ambiguous[3] == ["duplicate_school_candidates_require_review"]


def test_ts_rows_missing_ne_or_adjustment_are_in_review_report(tmp_path):
	canonical_path = _write_workbook(
		tmp_path / "school-seed.xlsx",
		"Canonical schools",
		SEED_HEADERS,
		[["01", "TP.HCM", "011", "Ward", "S001", "THPT Nguyễn Du", "1 Main Street"]],
	)
	ts_path = _write_workbook(
		tmp_path / "ts.xlsx",
		importer.PRIMARY_TS_SHEET,
		["Tên tỉnh", "Tên trường", "NE 2025", "Số điều chỉnh", "Target 2026"],
		[
			["Bình Dương", "THPT Nguyễn Du", None, 10, 20],
			["Bình Dương", "THPT Nguyễn Du", 12, None, 20],
		],
	)

	report = importer.reconcile_ts_workbook(ts_path, canonical_path=canonical_path)

	assert {row["source_row"] for row in report["review_rows"]} == {3, 4}


def test_compact_json_inputs_round_trip_from_excel(tmp_path):
	canonical_xlsx = _write_workbook(
		tmp_path / "school-seed.xlsx",
		"Canonical schools",
		SEED_HEADERS,
		[["01", "TP.HCM", "011", "Ward", "S001", "THPT Nguyễn Du", "1 Main Street"]],
	)
	canonical_json = tmp_path / "school-seed.json"
	extractor.extract_school_seed(canonical_xlsx, canonical_json)

	ts_xlsx = _write_workbook(
		tmp_path / "ts.xlsx",
		importer.PRIMARY_TS_SHEET,
		["Tên tỉnh", "Tên trường", "NE 2025", "Target 2026"],
		[["Bình Dương", "THPT Nguyễn Du", 12, 20]],
	)
	ts_json = tmp_path / "ts.json"
	extractor.extract_ts_workbook(ts_xlsx, ts_json)

	canonical_payload = json.loads(canonical_json.read_text(encoding="utf-8"))
	ts_payload = json.loads(ts_json.read_text(encoding="utf-8"))
	assert isinstance(canonical_payload["rows"][0], list)
	assert isinstance(ts_payload["rows"][0], list)
	assert importer.reconcile_school_seed(canonical_json)["total_rows"] == 1
	report = importer.reconcile_ts_workbook(ts_json, canonical_path=canonical_json)
	assert report["source_file"] == "ts.xlsx"
	assert report["total_rows"] == 1
	assert report["status_counts"] == {"matched": 1}


def test_ne_2026_supplement_resolves_explicit_canonical_targets(tmp_path, monkeypatch):
	supplement_path = tmp_path / "ne-2026.json"
	supplement_path.write_text(
		json.dumps({
			"source_file": "TS-HCM-2026.xlsx",
			"source_sheet": "NE 2026 bổ sung",
			"rows": [{
				"source_row": 2,
				"province_name": "TP.HCM",
				"school_name": "THPT Nguyễn Du",
				"ne_2026": 7,
				"canonical_source_identity": "01:011:S001",
			}],
		}, ensure_ascii=False),
		encoding="utf-8",
	)
	monkeypatch.setattr(importer, "NE_2026_SUPPLEMENT_PATH", supplement_path)

	_supplement, rows = importer._resolve_ne_2026_supplement({
		"01:011:S001": {"source_identity": "01:011:S001"},
	}, "TS-HCM-2026.json")

	assert rows[0]["match_status"] == "matched"
	assert rows[0]["ne_2026"] == 7


def test_ts_pic_falls_back_to_promoter_owner(monkeypatch):
	class _PromoterDB:
		def get_value(self, doctype, filters, _field):
			assert doctype == "CRM Staff"
			assert filters == {"user": importer.TS_PROMOTER_OWNER_USER}
			return "PROMOTER-STAFF"

	class _PromoterFrappe:
		db = _PromoterDB()

	monkeypatch.setattr(importer, "frappe", _PromoterFrappe())
	monkeypatch.setattr(importer, "_resolve_staff", lambda _alias: (None, None))

	assert importer._resolve_ts_promoter_owner("PIC alias") == ("PROMOTER-STAFF", None)


def test_snapshot_import_maps_history_to_matching_admission_years(monkeypatch, tmp_path):
	captured = []
	monkeypatch.setattr(importer, "_ensure_admission_year", lambda year: str(year))
	monkeypatch.setattr(
		importer,
		"_upsert",
		lambda doctype, filters, values: (captured.append((doctype, filters, values)) or (None, "created")),
	)
	record = {
		"source_sheet": importer.PRIMARY_TS_SHEET,
		"source_row": 7,
		"candidate": {"name": "HS-1"},
		"data": {"ne_2022": "8", "ne_2025": "12", "target_2026": "20"},
	}

	created = importer._import_snapshot(record, tmp_path / "TS HCM 2026.xlsx")

	assert created == 3
	assert [(row[1]["admission_year"], row[2]["ne_actual"], row[2]["ne_target"]) for row in captured] == [
		("2022", 8, None),
		("2025", 12, None),
		("2026", None, 20),
	]
	assert all(row[2]["adjusted_ne_threshold"] == 10 for row in captured)


def test_conflicting_source_code_is_not_silently_matched_by_name():
	seed_rows = [_seed_row("Tp. Hồ Chí Minh", "THPT Nguyễn Du", "S001")]
	by_name, by_global_name, by_identity = importer._school_index(seed_rows)

	_match, status, _confidence, reasons = importer._match_school(
		{
			"province_name": "TP.HCM",
			"school_name": "THPT Nguyễn Du",
			"school_code": "WRONG-CODE",
			"address": "",
		},
		by_name,
		by_global_name,
		by_identity,
	)

	assert _match is None
	assert status == "unmatched"
	assert reasons == ["school_code_not_found"]


def test_explicit_manual_mapping_wins_over_duplicate_name_candidates(monkeypatch):
	seed_rows = [
		_seed_row("Tp. Hồ Chí Minh", "THPT Nguyễn Du", "S001", ward_code="011"),
		_seed_row("Tp. Hồ Chí Minh", "THPT Nguyễn Du", "S002", ward_code="012"),
	]
	by_name, by_global_name, by_identity = importer._school_index(seed_rows)
	monkeypatch.setitem(importer.MANUAL_SCHOOL_MAPPINGS, "Source:7", "01:012:S002")

	matched = importer._match_school(
		{"province_name": "TP.HCM", "school_name": "THPT Nguyễn Du", "school_code": "", "address": ""},
		by_name,
		by_global_name,
		by_identity,
		source_sheet="Source",
		source_row=7,
	)

	assert matched[1:4] == ("matched", 1.0, ["manual_canonical_mapping"])
	assert matched[0]["source_identity"] == "01:012:S002"


def test_khu_vuc_accepts_legacy_school_code_when_name_and_province_are_unique():
	seed_rows = [_seed_row("Tp. Hồ Chí Minh", "THPT Nguyễn Du", "NEW-CODE")]
	by_name, by_global_name, by_identity = importer._school_index(seed_rows)

	matched = importer._match_school(
		{"province_name": "TP.HCM", "school_name": "THPT Nguyễn Du", "school_code": "OLD-CODE", "address": ""},
		by_name,
		by_global_name,
		by_identity,
		source_sheet="KHU VỰC 1",
		source_row=2,
	)

	assert matched[1:4] == (
		"matched",
		0.88,
		["normalized_name_and_province", "legacy_school_code_changed"],
	)


class _NoWriteFrappe:
	def __getattr__(self, name):
		raise AssertionError(f"dry-run accessed Frappe write API: {name}")


def test_school_seed_dry_run_never_calls_frappe_api(tmp_path, monkeypatch):
	path = _write_workbook(
		tmp_path / "school-seed.xlsx",
		"Canonical schools",
		SEED_HEADERS,
		[["01", "TP.HCM", "011", "Ward", "S001", "THPT Nguyễn Du", "1 Main Street"]],
	)
	monkeypatch.setattr(importer, "frappe", _NoWriteFrappe())

	result = importer.seed_school_seed(path, dry_run=True)

	assert result["dry_run"] is True
	assert result["mutations"] == {}
	assert result["report"]["total_rows"] == 1


def test_ts_dry_run_never_calls_frappe_api(tmp_path, monkeypatch):
	canonical_path = _write_workbook(
		tmp_path / "school-seed.xlsx",
		"Canonical schools",
		SEED_HEADERS,
		[["01", "TP.HCM", "011", "Ward", "S001", "THPT Nguyễn Du", "1 Main Street"]],
	)
	ts_path = _write_workbook(
		tmp_path / "ts.xlsx",
		importer.PRIMARY_TS_SHEET,
		["Tên tỉnh", "Tên trường"],
		[["Bình Dương", "THPT Nguyễn Du"]],
	)
	monkeypatch.setattr(importer, "frappe", _NoWriteFrappe())

	result = importer.seed_ts_workbook(ts_path, canonical_path=canonical_path, dry_run=True)

	assert result["dry_run"] is True
	assert result["mutations"] == {}
	assert result["report"]["total_rows"] == 1


class _SeedDB:
	def __init__(self):
		self.commits = 0
		self.savepoints = []

	def get_value(self, doctype, _filters, _field):
		return "HS-1" if doctype == "CRM High School" else None

	def commit(self):
		self.commits += 1

	def savepoint(self, name):
		self.savepoints.append(name)

	def rollback(self, **_kwargs):
		return None


class _SeedFrappe:
	def __init__(self):
		self.db = _SeedDB()

	def only_for(self, *_args):
		return None


def test_non_dry_run_matched_row_has_no_candidate_shape_error(tmp_path, monkeypatch):
	canonical_path = _write_workbook(
		tmp_path / "school-seed.xlsx",
		"Canonical schools",
		SEED_HEADERS,
		[["01", "TP.HCM", "011", "Ward", "S001", "THPT Nguyễn Du", "1 Main Street"]],
	)
	ts_path = _write_workbook(
		tmp_path / "ts.xlsx",
		importer.PRIMARY_TS_SHEET,
		["Tên tỉnh", "Tên trường"],
		[["Bình Dương", "THPT Nguyễn Du"]],
	)
	fake_frappe = _SeedFrappe()
	monkeypatch.setattr(importer, "frappe", fake_frappe)

	result = importer.seed_ts_workbook(ts_path, canonical_path=canonical_path, dry_run=False)

	assert result["errors"] == []
	assert result["mutations"] == {}
	assert fake_frappe.db.commits == 1
