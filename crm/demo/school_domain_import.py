"""Dry-run-first import adapters for the school domain workbooks.

The workbooks are operational inputs and intentionally live outside the
repository.  This module exposes pure reconciliation functions plus explicit
``dry_run=False`` seed functions; a dry run never calls a Frappe write API.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import frappe

# The workbooks are gitignored operational inputs (they carry PIC PII). Drop them
# next to this module under ``data/`` and both the importers and ``seed_showcase``
# pick them up with no path argument; an absolute ``path=`` still overrides.
_DATA_DIR = Path(__file__).parent / "data"
DEFAULT_SCHOOL_SEED_PATH = _DATA_DIR / "school-seed.json"
DEFAULT_TS_PATH = _DATA_DIR / "TS-HCM-2026.json"
DEFAULT_SCHOOL_SEED_XLSX_PATH = _DATA_DIR / "school-seed.xlsx"
DEFAULT_TS_XLSX_PATH = _DATA_DIR / "TS-HCM-2026.xlsx"
NE_2026_SUPPLEMENT_PATH = _DATA_DIR / "reference" / "ts_hcm_2026_ne_2026.json"
# Must match the Promoter account created by
# crm.demo.seed_showcase._ensure_promoter_fixture (PROMOTER_EMAIL); the TS import
# assigns every workbook relationship to that portfolio.
TS_PROMOTER_OWNER_USER = "vo.thi.lan@gmail.com"
MANUAL_SCHOOL_MAPPING_PATH = _DATA_DIR / "reference" / "ts_school_manual_mapping.json"
PRIMARY_TS_SHEET = "Địa bàn TĐ THPT 2026"
KEY_ACCOUNT_SOURCE_SHEETS = frozenset({PRIMARY_TS_SHEET})
TS_ACTIVITY_SHEET_MARKERS = ("lịch chương trình", "lịch công tác")
TS_NON_SCHOOL_SHEET_MARKERS = ("báo cáo", "lịch sự kiện", "tổng hợp", "aggregate")
ANNUAL_YEARS = (2022, 2023, 2024, 2025, 2026)

# The canonical JSON remains the complete operational directory.  Showcase
# data uses a small, deterministic slice so a local demo site stays usable.
DEMO_SCHOOLS_PER_PROVINCE = 10
DEMO_CANONICAL_PROVINCES = (
	"Khánh Hoà",
	"Đắk Lắk",
	"Lâm Đồng",
	"TP. Đồng Nai",
	"Tp. Hồ Chí Minh",
	"Tây Ninh",
	"Đồng Tháp",
)
_DEMO_EXCLUDED_SCHOOL_MARKERS = ("khu vuc", "hoc o nuoc ngoai")
_DEMO_PREFERRED_SCHOOL_MARKERS = ("thpt", "thcs", "pho thong")
_SCHOOL_DOMAIN_CHILD_LINKS = (
	("CRM High School Annual Snapshot", "high_school"),
	("CRM School Activity", "high_school"),
	("CRM School Stakeholder", "high_school"),
	("CRM School Contact", "high_school"),
	("CRM School Relationship", "high_school"),
	("CRM Student Geography Snapshot", "high_school"),
)
_SCHOOL_DOMAIN_PROTECTED_LINKS = (
	("CRM Student", "high_school"),
	("CRM Contact", "high_school"),
)


def _normalize(value) -> str:
	value = str(value or "").replace("Đ", "D").replace("đ", "d")
	value = unicodedata.normalize("NFD", str(value or ""))
	value = "".join(char for char in value if unicodedata.category(char) != "Mn")
	return re.sub(r"[^a-zA-Z0-9]+", " ", value).strip().casefold()


def _text(value) -> str:
	if value is None:
		return ""
	if isinstance(value, (datetime, date)):
		return value.isoformat()
	if isinstance(value, float) and value.is_integer():
		return str(int(value))
	return str(value).replace("\n", " ").strip()


def _number(value):
	value = _text(value).replace(",", "").replace(" ", "")
	if not value:
		return None
	try:
		return int(float(value))
	except (TypeError, ValueError):
		return None


def _coordinate(value):
	"""Parse a geocoded latitude/longitude cell; blank or non-numeric yields ``None``."""
	value = _text(value)
	if not value:
		return None
	try:
		return round(float(value), 7)
	except (TypeError, ValueError):
		return None


def _load_aliases():
	path = Path(__file__).parent / "data" / "reference" / "legacy_province_aliases.json"
	return json.loads(path.read_text(encoding="utf-8"))["aliases"]


PROVINCE_ALIASES = _load_aliases()
PROVINCE_BY_ALIAS = {
	_normalize(alias): canonical
	for canonical, aliases in PROVINCE_ALIASES.items()
	for alias in {canonical, *aliases}
}


def _load_manual_school_mappings():
	if not MANUAL_SCHOOL_MAPPING_PATH.exists():
		return {}, 0
	payload = json.loads(MANUAL_SCHOOL_MAPPING_PATH.read_text(encoding="utf-8"))
	source_file = payload.get("source_file", "")
	source_files = {source_file, source_file.replace("-", " ")} if source_file else {""}
	mappings = {
		f"{file_name}:{key}" if file_name else key: value
		for file_name in source_files
		for key, value in payload.get("mappings", {}).items()
	}
	return mappings, len(payload.get("mappings", {}))


MANUAL_SCHOOL_MAPPINGS, MANUAL_SCHOOL_MAPPINGS_CONFIGURED = _load_manual_school_mappings()


def canonical_province_name(value: str | None) -> str | None:
	return PROVINCE_BY_ALIAS.get(_normalize(value))


def normalize_school_name(value: str | None) -> str:
	value = _normalize(value)
	return re.sub(
		r"\b(truong|thpt|thcs|th|ptdtnt|dtnt|pt|hoc|pho thong|dan toc noi tru|high school|va)\b",
		" ",
		value,
	).strip()


def source_identity(province_code, ward_code, school_code) -> str:
	return ":".join(_text(value) for value in (province_code, ward_code, school_code))


def _header_key(value) -> str | None:
	normalized = _normalize(value).replace(" ", "")
	if normalized in {"stt", "no", "number"}:
		return "row_number"
	if normalized in {"diaban", "tinhdiaban", "tinhthanh"}:
		return "province_name"
	if normalized in {"matinhtp", "matinh", "matinhthanhpho", "provincecode"}:
		return "province_code"
	if normalized in {"tentinhtp", "tentinh", "tentinhthanhpho", "province", "tinh", "tinhthanhpho"}:
		return "province_name"
	if normalized in {"maxaphuong", "maxa", "maphuong", "maphuongxa", "maxaphuongthitran", "wardcode"}:
		return "ward_code"
	if normalized in {"tenxaphuong", "tenxa", "tenphuong", "phuongxa", "tenphuongxa", "tenxaphuongthitran", "ward", "wardname"}:
		return "ward_name"
	if normalized in {"matruong", "schoolcode", "code"}:
		return "school_code"
	if normalized in {"tentruong", "school", "schoolname", "tentruongthpt", "truongthpt", "truong"}:
		return "school_name"
	if normalized in {"diachi", "address", "diachitruong"} or normalized.startswith("diachitruong"):
		return "address"
	if normalized in {"latitude", "lat", "vido"}:
		return "latitude"
	if normalized in {"longitude", "long", "lng", "lon", "kinhdo"}:
		return "longitude"
	if normalized in {"loaihinh", "loaitruong", "schooltype", "type"}:
		return "school_type"
	if normalized in {"khuvuc", "schoolarea", "area", "kv"}:
		return "school_area"
	if normalized in {"pic", "phutrach", "nguoiphutrach", "owner", "ownerstaff"}:
		return "pic"
	if "phutrach" in normalized and "cb" in normalized:
		return "stakeholder_name"
	if normalized in {"team", "nhom", "donvi", "bophan", "phancongteam"}:
		return "team"
	if normalized in {"sodieuchinh", "adjustednethreshold", "adjustment", "threshold"}:
		return "adjusted_ne_threshold"
	if normalized in {"target2026", "target26", "ne2026target", "muctieu2026"}:
		return "target_2026"
	if normalized in {"ne2022", "newenter2022"}:
		return "ne_2022"
	if normalized in {"ne2023", "newenter2023"}:
		return "ne_2023"
	if normalized in {"ne2024", "newenter2024"}:
		return "ne_2024"
	if normalized in {"ne2025", "newenter2025"}:
		return "ne_2025"
	if normalized in {"stakeholder", "stakeholdername", "nguoilienhe", "dautuyensinh", "dautuyensinhthpt"}:
		return "stakeholder_name"
	if normalized in {"promoter", "tenpromoterlienhe", "tenpromoterphutrach", "promoterphutrach"}:
		return "pic"
	if normalized == "cbcongtac":
		return "pic"
	if normalized in {"stakeholderrole", "vaitro", "chucvu", "role"}:
		return "stakeholder_role"
	if normalized in {"phone", "sodienthoai", "dienthoai", "mobile", "sodt"}:
		return "stakeholder_phone"
	if normalized in {"email", "emailstakeholder", "thudientu"}:
		return "stakeholder_email"
	if normalized in {"activity", "activitytype", "hoatdong", "noidung", "chuongtrinh", "sukien", "tensukien"}:
		return "activity_type"
	if normalized in {"date", "ngay", "ngaythuchien", "thoigian", "ngaythang"} or normalized.startswith("ngaythang"):
		return "activity_date"
	if normalized in {"status", "trangthai"}:
		return "status"
	if normalized in {"outcome", "ketqua"}:
		return "outcome"
	return None


def _date_value(value):
	value = _text(value)
	if not value:
		return None
	for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
		try:
			return datetime.strptime(value[:10], fmt).date().isoformat()
		except ValueError:
			continue
	return value[:10]


def _find_header_row(rows):
	best = (None, {})
	for index, row in enumerate(rows[:40]):
		headers = {}
		for column, value in enumerate(row):
			key = _header_key(value)
			if key and key not in headers:
				headers[key] = column
		if len(headers) > len(best[1]):
			best = (index, headers)
		if len(headers) >= 2 and {"school_name", "province_name", "activity_type"} & set(headers):
			return index, headers
	if best[0] is None or len(best[1]) < 2:
		return None, {}
	return best


def _workbook(path):
	try:
		from openpyxl import load_workbook
	except ImportError:
		frappe.throw("openpyxl is required for school workbook imports.")
	path = Path(path)
	if not path.exists():
		frappe.throw(f"Workbook not found: {path}")
	return load_workbook(path, data_only=True, read_only=True)


def _json_payload(path):
	try:
		return json.loads(Path(path).read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError) as exc:
		frappe.throw(f"Invalid school-domain JSON input: {path} ({exc})")


def _json_rows(payload, *, canonical=False):
	fields = payload.get("fields", [])
	for row in payload.get("rows", []):
		if isinstance(row, dict):
			yield dict(row)
			continue
		if canonical:
			source_row, values = row
			source_sheet = payload.get("source_sheet", "")
		else:
			source_sheet, source_row, values = row
		data = {
			field: value
			for field, value in zip(fields, values, strict=True)
			if value not in (None, "")
		}
		yield {"source_sheet": source_sheet, "source_row": source_row, "data": data}


def _source_file_name(path):
	path = Path(path)
	if path.suffix.casefold() == ".json":
		return _json_payload(path).get("source_file", path.name)
	return path.name


def profile_workbook(path) -> dict:
	"""Return sheet dimensions only; no cell values are returned."""
	if Path(path).suffix.casefold() == ".json":
		payload = _json_payload(path)
		return payload.get("profile", {"source_file": _source_file_name(path), "sheets": []})
	workbook = _workbook(path)
	try:
		return {
			"source_file": Path(path).name,
			"sheets": [
				{"name": sheet.title, "rows": sheet.max_row, "columns": sheet.max_column}
				for sheet in workbook.worksheets
			],
		}
	finally:
		workbook.close()


def _sheet_records(sheet):
	rows = list(sheet.iter_rows(values_only=True))
	header_row, headers = _find_header_row(rows)
	if header_row is None:
		return [], {"status": "unresolved", "reason": "header_not_found"}
	records = []
	for row_number, row in enumerate(rows[header_row + 1 :], start=header_row + 2):
		values = {key: _text(row[index]) if index < len(row) else "" for key, index in headers.items()}
		if not any(values.values()):
			continue
		records.append({"source_row": row_number, "data": values})
	return records, {"status": "ready", "header_row": header_row + 1, "columns": sorted(headers)}


def _sanitized_row(record):
	data = record.get("data", {})
	return {
		"source_sheet": record.get("source_sheet"),
		"source_row": record.get("source_row"),
		"school_name": data.get("school_name"),
		"province_name": data.get("province_name"),
		"school_code": data.get("school_code"),
		"source_identity": record.get("source_identity") or record.get("canonical_source_identity"),
		"match_status": record.get("match_status"),
		"confidence": record.get("confidence"),
		"review_required": record.get("review_required", False),
		"reasons": record.get("reasons", []),
	}


def _demo_school_sort_key(record):
	name = _normalize(record.get("data", {}).get("school_name"))
	excluded = any(marker in name for marker in _DEMO_EXCLUDED_SCHOOL_MARKERS)
	preferred = any(marker in name for marker in _DEMO_PREFERRED_SCHOOL_MARKERS)
	return (
		1 if excluded else 0,
		0 if preferred else 1,
		_number(record.get("source_row")) or 0,
		record.get("source_identity") or "",
	)


def select_demo_school_rows(rows, *, schools_per_province=DEMO_SCHOOLS_PER_PROVINCE):
	"""Return a stable, representative school slice for the local showcase."""
	if not isinstance(schools_per_province, int) or schools_per_province <= 0:
		raise ValueError("schools_per_province must be a positive integer")

	allowed_provinces = set(DEMO_CANONICAL_PROVINCES)
	grouped = defaultdict(list)
	for record in rows:
		if record.get("match_status") != "ready":
			continue
		province = record.get("canonical_province")
		if province in allowed_provinces:
			grouped[province].append(record)

	missing = [
		province
		for province in DEMO_CANONICAL_PROVINCES
		if len(grouped[province]) < schools_per_province
	]
	if missing:
		raise ValueError(
			f"not enough ready schools for demo provinces: {', '.join(missing)}"
		)

	selected = []
	for province in DEMO_CANONICAL_PROVINCES:
		selected.extend(sorted(grouped[province], key=_demo_school_sort_key)[:schools_per_province])
	return sorted(selected, key=lambda record: _number(record.get("source_row")) or 0)


def _demo_school_seed_report(report, schools_per_province):
	selected = select_demo_school_rows(report["rows"], schools_per_province=schools_per_province)
	return {
		**report,
		"total_rows": len(selected),
		"status_counts": dict(Counter(row["match_status"] for row in selected)),
		"canonical_provinces": list(DEMO_CANONICAL_PROVINCES),
		"rows": selected,
		"review_rows": [_sanitized_row(row) for row in selected if row["match_status"] != "ready"],
		"demo_selection": {
			"schools_per_province": schools_per_province,
			"total_schools": len(selected),
		},
	}


def reconcile_school_seed(path=DEFAULT_SCHOOL_SEED_PATH) -> dict:
	path = Path(path)
	workbook = None
	try:
		if path.suffix.casefold() == ".json":
			payload = _json_payload(path)
			records = list(_json_rows(payload, canonical=True))
			sheet_title = payload.get("source_sheet", "Canonical schools")
			sheet_info = payload.get("sheet", {"status": "ready"})
		else:
			workbook = _workbook(path)
			sheet = workbook.active
			records, sheet_info = _sheet_records(sheet)
			sheet_title = sheet.title
		seen = set()
		rows = []
		status_counts = Counter()
		for record in records:
			data = record["data"]
			record["source_sheet"] = record.get("source_sheet") or sheet_title
			province = canonical_province_name(data.get("province_name"))
			identity = source_identity(data.get("province_code"), data.get("ward_code"), data.get("school_code"))
			reasons = []
			if not province:
				reasons.append("unknown_canonical_province")
			if not all(data.get(field) for field in ("province_code", "ward_code", "school_code", "school_name")):
				reasons.append("missing_composite_identity")
			if identity in seen:
				reasons.append("duplicate_composite_identity")
			seen.add(identity)
			record["canonical_province"] = province
			record["source_identity"] = identity
			record["source_pic_fingerprint"] = (
			hashlib.sha256(_text(data.get("pic")).encode("utf-8")).hexdigest()[:16]
			if data.get("pic") else None
		)
			record["match_status"] = "ready" if not reasons else "review_required"
			record["reasons"] = reasons
			status_counts[record["match_status"]] += 1
			rows.append(record)
		return {
			"source_file": _source_file_name(path),
			"source_sheet": sheet_title,
			"sheet": sheet_info,
			"total_rows": len(rows),
			"status_counts": dict(status_counts),
			"canonical_provinces": sorted({row["canonical_province"] for row in rows if row["canonical_province"]}),
			"rows": rows,
			"review_rows": [_sanitized_row(row) for row in rows if row["match_status"] != "ready"],
		}
	finally:
		if workbook:
			workbook.close()


def _school_index(seed_rows):
	by_name = defaultdict(list)
	by_global_name = defaultdict(list)
	by_identity = {}
	for record in seed_rows:
		if record.get("match_status") != "ready":
			continue
		data = record["data"]
		candidate = {
			"high_school": data.get("school_name"),
			"province_name": record["canonical_province"],
			"province_code": data.get("province_code"),
			"ward_code": data.get("ward_code"),
			"school_code": data.get("school_code"),
			"ward_name": data.get("ward_name"),
			"address": data.get("address"),
			"source_identity": record["source_identity"],
		}
		by_name[(record["canonical_province"], normalize_school_name(data.get("school_name")))].append(candidate)
		by_global_name[normalize_school_name(data.get("school_name"))].append(candidate)
		by_identity[record["source_identity"]] = candidate
	return by_name, by_global_name, by_identity


def _match_school(data, by_name, by_global_name, by_identity, *, source_file=None, source_sheet=None, source_row=None):
	manual_key = None
	if source_sheet and source_row:
		manual_key = f"{source_file}:{source_sheet}:{source_row}" if source_file else f"{source_sheet}:{source_row}"
	manual_identity = MANUAL_SCHOOL_MAPPINGS.get(manual_key)
	if manual_identity:
		candidate = by_identity.get(manual_identity)
		if candidate:
			return candidate, "matched", 1.0, ["manual_canonical_mapping"]
		return None, "unmatched", 0, ["manual_mapping_target_not_found"]
	province = canonical_province_name(data.get("province_name"))
	name = normalize_school_name(data.get("school_name"))
	if not name:
		return None, "unmatched", 0, ["missing_school_name"]
	if province:
		candidates = list(by_name.get((province, name), []))
	else:
		candidates = list(by_global_name.get(name, []))
	if not candidates:
		return None, "unmatched", 0, ["unknown_canonical_province"] if not province else ["school_name_province_not_found"]
	if len(candidates) == 1:
		if data.get("school_code") and candidates[0].get("school_code") and data["school_code"] != candidates[0]["school_code"]:
			if source_sheet == "KHU VỰC 1":
				return candidates[0], "review_required", 0.88, ["normalized_name_and_province", "legacy_school_code_changed"]
			return None, "unmatched", 0, ["school_code_not_found"]
		if province and data.get("school_code") == candidates[0].get("school_code"):
			return candidates[0], "matched", 0.98, ["name_province_and_source_code"]
		if province:
			return candidates[0], "review_required", 0.9, ["normalized_name_and_province_require_review"]
		return candidates[0], "review_required", 0.75, ["unique_school_name_without_province"]
	if data.get("school_code"):
		by_code = [row for row in candidates if row["school_code"] == data["school_code"]]
		if len(by_code) == 1:
			return by_code[0], "matched", 0.98, ["name_province_and_source_code"]
	address = _normalize(data.get("address"))
	if address:
		by_address = [
			row for row in candidates
			if _normalize(row.get("address")) == address
			or address in _normalize(row.get("address"))
			or _normalize(row.get("address")) in address
		]
		if len(by_address) == 1:
			return by_address[0], "matched", 0.97, ["name_province_and_address"]
	return None, "ambiguous", 0, ["duplicate_school_candidates_require_review"]


def _sheet_kind(sheet_name):
	normalized = _normalize(sheet_name)
	if normalized == _normalize(PRIMARY_TS_SHEET):
		return "primary"
	if any(_normalize(marker) in normalized for marker in TS_ACTIVITY_SHEET_MARKERS):
		return "activity"
	if any(_normalize(marker) in normalized for marker in TS_NON_SCHOOL_SHEET_MARKERS):
		return "aggregate_or_calendar"
	return "reference"


def _ts_input_sheets(path):
	path = Path(path)
	if path.suffix.casefold() == ".json":
		payload = _json_payload(path)
		grouped = defaultdict(list)
		for record in _json_rows(payload):
			grouped[record.get("source_sheet", "")].append(record)
		items = []
		for sheet in payload.get("sheets", []):
			name = sheet.get("name", "")
			items.append((name, sheet.get("kind") or _sheet_kind(name), grouped.pop(name, []), sheet.get("profile", {})))
		for name, records in grouped.items():
			items.append((name, _sheet_kind(name), records, {"status": "ready"}))
		return _source_file_name(path), items
	workbook = _workbook(path)
	try:
		return _source_file_name(path), [
			(sheet.title, _sheet_kind(sheet.title), *(_sheet_records(sheet)))
			for sheet in workbook.worksheets
		]
	finally:
		workbook.close()


def _is_ts_hcm_source(path) -> bool:
	return _normalize(Path(path).stem) == "ts hcm 2026"


def _load_ne_2026_supplement(path=None):
	if path is not None and not _is_ts_hcm_source(path):
		return {"source_file": "TS-HCM-2026.xlsx", "source_sheet": "NE 2026 bổ sung", "rows": []}
	if not NE_2026_SUPPLEMENT_PATH.exists():
		return {"source_file": "TS-HCM-2026.xlsx", "source_sheet": "NE 2026 bổ sung", "rows": []}
	payload = _json_payload(NE_2026_SUPPLEMENT_PATH)
	return {
		"source_file": payload.get("source_file", "TS-HCM-2026.xlsx"),
		"source_sheet": payload.get("source_sheet", "NE 2026 bổ sung"),
		"rows": payload.get("rows", []),
	}


def _resolve_ne_2026_supplement(by_identity, path=None):
	rows = _load_ne_2026_supplement(path)
	resolved = []
	for index, row in enumerate(rows["rows"], start=1):
		identity = row.get("canonical_source_identity")
		candidate = by_identity.get(identity)
		resolved.append({
			"source_row": row.get("source_row", index),
			"province_name": row.get("province_name"),
			"school_name": row.get("school_name"),
			"ne_2026": row.get("ne_2026"),
			"canonical_source_identity": identity,
			"candidate": candidate,
			"match_status": "matched" if candidate else "unmatched",
		})
	return rows, resolved


def reconcile_ts_workbook(path=DEFAULT_TS_PATH, *, canonical_path=DEFAULT_SCHOOL_SEED_PATH, canonical_rows=None) -> dict:
	seed = canonical_rows or reconcile_school_seed(canonical_path)["rows"]
	by_name, by_global_name, by_identity = _school_index(seed)
	rows = []
	sheet_summaries = []
	expected = {PRIMARY_TS_SHEET, "KHU VỰC 1", "LỊCH CHƯƠNG TRÌNH", "LỊCH CÔNG TÁC", "LỊCH SỰ KIỆN"}
	source_file, input_sheets = _ts_input_sheets(path)
	found_normalized = {_normalize(name) for name, _kind, _records, _info in input_sheets}
	for expected_sheet in expected:
		if _normalize(expected_sheet) not in found_normalized:
			sheet_summaries.append({"sheet": expected_sheet, "status": "review_required", "reason": "sheet_not_found"})
	for sheet_name, kind, records, info in input_sheets:
		sheet_status = Counter()
		for record in records:
			data = record["data"]
			record["source_sheet"] = record.get("source_sheet") or sheet_name
			record["import_kind"] = kind
			candidate, status, confidence, reasons = _match_school(
				data,
				by_name,
				by_global_name,
				by_identity,
				source_file=source_file,
				source_sheet=record["source_sheet"],
				source_row=record["source_row"],
			)
			record["canonical_source_identity"] = candidate.get("source_identity") if candidate else None
			record["source_pic_fingerprint"] = (
				hashlib.sha256(_text(data.get("pic")).encode("utf-8")).hexdigest()[:16]
				if data.get("pic") else None
			)
			if kind == "aggregate_or_calendar" and not data.get("school_name"):
				status, confidence, reasons = "unmatched", 0, ["aggregate_or_calendar_without_school_grain"]
			if kind == "primary":
				if any(not data.get(f"ne_{year}") for year in (2022, 2023, 2024, 2025)):
					reasons.append("missing_ne_value")
				if not data.get("adjusted_ne_threshold"):
					reasons.append("missing_adjusted_ne_threshold")
			if data.get("stakeholder_name"):
				reasons.append("person_manual_review_required")
			record.update({
				"candidate": candidate,
				"match_status": status,
			"confidence": confidence,
			"reasons": reasons,
			"review_required": bool(reasons),
			})
			sheet_status[status] += 1
			rows.append(record)
		sheet_summaries.append({"sheet": sheet_name, "kind": kind, "profile": info, "status_counts": dict(sheet_status)})
	supplement, supplement_rows = _resolve_ne_2026_supplement(by_identity, path)
	supplement_matched = [row for row in supplement_rows if row["match_status"] == "matched"]
	supplement_targets = {row["canonical_source_identity"] for row in supplement_matched}
	result = {
		"source_file": source_file,
		"canonical_source_file": Path(canonical_path).name,
		"manual_mapping_file": MANUAL_SCHOOL_MAPPING_PATH.name,
		"manual_mappings_configured": MANUAL_SCHOOL_MAPPINGS_CONFIGURED,
		"manual_mappings_applied": sum("manual_canonical_mapping" in row.get("reasons", []) for row in rows),
		"ne_2026_supplement": {
			"source_file": supplement["source_file"],
			"source_sheet": supplement["source_sheet"],
			"total_rows": len(supplement_rows),
			"matched_rows": len(supplement_matched),
			"aggregated_canonical_targets": len(supplement_targets),
			"unmatched_rows": len(supplement_rows) - len(supplement_matched),
		},
		"_ne_2026_rows": supplement_rows,
		"source_sheets": sheet_summaries,
		"total_rows": len(rows),
		"status_counts": dict(Counter(row["match_status"] for row in rows)),
		"rows": rows,
		"review_rows": [_sanitized_row(row) for row in rows if row["match_status"] != "matched" or row.get("review_required")],
	}
	return result


def _public_reconciliation_report(report: dict) -> dict:
	"""Return review metadata without raw workbook rows or contact PII."""
	public = {key: value for key, value in report.items() if key not in {"rows", "_ne_2026_rows"}}
	public["review_rows"] = [
		{key: value for key, value in row.items() if key not in {"data", "candidate"}}
		for row in report.get("review_rows", [])
	]
	public["provenance_rows"] = [
		{
			"source_sheet": row.get("source_sheet"),
			"source_row": row.get("source_row"),
			"source_identity": row.get("source_identity") or row.get("canonical_source_identity"),
			"source_pic_fingerprint": row.get("source_pic_fingerprint"),
			"match_status": row.get("match_status"),
		}
		for row in report.get("rows", [])
	]
	return public


def write_reconciliation_report(report: dict, path) -> str:
	"""Write a report without raw workbook rows or contact PII."""
	public = _public_reconciliation_report(report)
	path = Path(path)
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(public, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
	return str(path)


def _upsert(doctype, filters, values):
	name = frappe.db.get_value(doctype, filters, "name")
	if name:
		# Serialize concurrent updates for the unique business key. The initial
		# lookup identifies the row; the row lock makes the subsequent read/save
		# one transaction so a later importer cannot silently overwrite a stale
		# version observed by this importer.
		if hasattr(frappe.db, "sql"):
			frappe.db.sql(
				f"select name from `tab{doctype}` where name = %s for update",
				(name,),
			)
		doc = frappe.get_doc(doctype, name)
		changed = False
		for fieldname, value in values.items():
			if value is not None and doc.get(fieldname) != value:
				doc.set(fieldname, value)
				changed = True
		if changed:
			doc.save(ignore_permissions=True)
		return doc, "updated"
	doc = frappe.get_doc({"doctype": doctype, **values})
	try:
		doc.insert(ignore_permissions=True)
		return doc, "created"
	except Exception as exc:
		# Unique business-key indexes are the concurrency authority. If another
		# importer wins the insert race, re-read that row and apply the same
		# idempotent update instead of surfacing a duplicate or creating a second
		# identity.
		duplicate_error = getattr(frappe, "DuplicateEntryError", ())
		if not duplicate_error or not isinstance(exc, duplicate_error):
			raise
		name = frappe.db.get_value(doctype, filters, "name")
		if not name:
			raise
		doc = frappe.get_doc(doctype, name)
		# The concurrent winner is authoritative; do not overwrite it with the
		# losing transaction's potentially stale payload.
		return doc, "existing_after_race"


def _ensure_admission_year(year):
	name = str(year)
	if frappe.db.exists("CRM Admission Year", name):
		return name
	if frappe.db.exists("CRM Admission Year", {"year_name": name}):
		return frappe.db.get_value("CRM Admission Year", {"year_name": name}, "name")
	frappe.get_doc({"doctype": "CRM Admission Year", "year_name": name, "is_active": 1}).insert(ignore_permissions=True)
	return name


def _resolve_staff(alias):
	alias = _text(alias)
	if not alias:
		return None, None
	staff_rows = frappe.get_all("CRM Staff", fields=["name", "full_name", "user"], limit_page_length=0)
	for staff in staff_rows:
		user_aliases = {staff.full_name, staff.user}
		if _normalize(staff.full_name) == _normalize(alias) or _normalize(alias) in {
			_normalize(value.split("@", 1)[0]) for value in user_aliases if value
		}:
			team = frappe.db.get_value(
				"CRM Team Membership", {"parent": staff.name, "parenttype": "CRM Staff", "is_primary": 1}, "team"
			)
			return staff.name, team
	for user in frappe.get_all("User", fields=["name", "username"], limit_page_length=0):
		if _normalize(alias) in {_normalize(user.name), _normalize(user.username)}:
			staff = next((row for row in staff_rows if row.user == user.name), None)
			if staff:
				team = frappe.db.get_value(
					"CRM Team Membership",
					{"parent": staff.name, "parenttype": "CRM Staff", "is_primary": 1},
					"team",
				)
				return staff.name, team
	for team in frappe.get_all("CRM Team", fields=["name", "team_name"], limit_page_length=0):
		if _normalize(team.team_name) == _normalize(alias):
			return None, team.name
	return None, None


def _resolve_ts_promoter_owner(alias):
	"""Return the explicitly configured CRM owner/team for TS imports.

	The workbook PIC is provenance only and is deliberately not resolved into
	CRM ownership.
	"""
	# Source PIC is provenance only. CRM ownership always comes from the
	# explicitly configured import owner and its primary team.
	staff = frappe.db.get_value("CRM Staff", {"user": TS_PROMOTER_OWNER_USER}, "name")
	team = (
		frappe.db.get_value(
			"CRM Team Membership",
			{"parent": staff, "parenttype": "CRM Staff", "is_primary": 1},
			"team",
		)
		if staff
		else None
	)
	return staff, team


def _ts_owner_preflight(records):
	"""Resolve every owner before the first TS workbook mutation.

	A workbook containing only school/snapshot facts does not need a portfolio
	owner. Any Person or Activity row does: an unresolved configured owner, PIC,
	or team is a review-required import and cannot partially create records.
	"""
	issues = []
	for record in records:
		if record.get("match_status") != "matched":
			continue
		data = record.get("data", {})
		needs_owner = bool(data.get("stakeholder_name")) or record.get("import_kind") == "activity"
		if not needs_owner:
			continue
		staff, team = _resolve_ts_promoter_owner(None)
		if not staff:
			issues.append({
				"source_sheet": record.get("source_sheet"),
				"source_row": record.get("source_row"),
				"reason": "unresolved_import_owner",
			})
		elif not team:
			issues.append({
				"source_sheet": record.get("source_sheet"),
				"source_row": record.get("source_row"),
				"reason": "import_owner_team_unresolved",
			})
	return issues


def _blocking_review(record) -> bool:
	"""Return whether a reconciled row must be entirely write-blocked."""
	if record.get("match_status") != "matched":
		return True
	approved = {"manual_canonical_mapping", "name_province_and_source_code", "person_manual_review_required"}
	return any(reason not in approved for reason in record.get("reasons", ()))


def _school_db_filters(candidate):
	province = frappe.db.get_value("CRM Province", {"province_code": candidate.get("province_code")}, "name")
	ward = frappe.db.get_value(
		"CRM Ward",
		{"ward_code": candidate.get("ward_code"), "province": province},
		"name",
	)
	return {
		"school_code": candidate.get("school_code"),
		"province": province,
		"ward": ward,
	}


_TERM_DOCTYPE = {
	"school_type": "CRM School Type",
	"school_area": "CRM School Area",
	"stakeholder_role": "CRM Stakeholder Role",
	"activity_type": "CRM School Activity Type",
}


def _resolve_term(category, value):
	value = _text(value)
	doctype = _TERM_DOCTYPE.get(category)
	if not value or not doctype:
		return None
	for row in frappe.get_all(doctype, fields=["name", "display_name"], limit_page_length=0):
		if _normalize(row.display_name) == _normalize(value) or _normalize(row.name) == _normalize(value):
			return row.name
	return None


def seed_school_seed(
	path=DEFAULT_SCHOOL_SEED_PATH,
	*,
	dry_run=True,
	commit_policy="partial",
	max_schools_per_province=None,
):
	if commit_policy not in {"partial", "all"}:
		frappe.throw("commit_policy must be 'partial' or 'all'.")
	report = reconcile_school_seed(path)
	if max_schools_per_province is not None:
		report = _demo_school_seed_report(report, max_schools_per_province)
	if dry_run:
		return {
			"dry_run": True,
			"report": _public_reconciliation_report(report),
			"mutations": {},
			"commit_policy": commit_policy,
		}
	frappe.only_for("System Manager", True)
	counts = Counter()
	errors = []
	for record in report["rows"]:
		if record["match_status"] != "ready":
			counts["review_required"] += 1
			continue
		data = record["data"]
		savepoint = f"crm_school_seed_{record['source_row']}"
		frappe.db.savepoint(savepoint)
		try:
			province, state = _upsert(
				"CRM Province",
				{"province_code": data["province_code"]},
				{
					"province_code": data["province_code"],
					"province_name": record["canonical_province"],
				},
			)
			counts[f"province_{state}"] += 1
			ward, state = _upsert(
				"CRM Ward",
				{"ward_code": data["ward_code"], "province": province.name},
				{
					"ward_code": data["ward_code"],
					"ward_name": data.get("ward_name"),
					"province": province.name,
					"province_name": record["canonical_province"],
				},
			)
			counts[f"ward_{state}"] += 1
			school_filters = {
				"school_code": data["school_code"],
				"province": province.name,
				"ward": ward.name,
			}
			school_area = _resolve_term("school_area", data.get("school_area")) if data.get("school_area") else None
			_school, state = _upsert(
				"CRM High School",
				school_filters,
				{
					"school_name": data["school_name"],
					"school_code": data["school_code"],
					"school_area": school_area,
					"province": province.name,
					"ward": ward.name,
					"address": data.get("address"),
					"latitude": _coordinate(data.get("latitude")),
					"longitude": _coordinate(data.get("longitude")),
				},
			)
			counts[f"school_{state}"] += 1
		except Exception as exc:
			frappe.db.rollback(save_point=savepoint)
			counts["errors"] += 1
			errors.append({"source_row": record["source_row"], "message": str(exc)})
	if commit_policy == "all" and errors:
		frappe.db.rollback()
		return {"dry_run": False, "report": report, "mutations": {}, "errors": errors, "commit_policy": commit_policy}
	frappe.db.commit()
	return {"dry_run": False, "report": report, "mutations": dict(counts), "errors": errors, "commit_policy": commit_policy}


def prune_school_seed(
	path=DEFAULT_SCHOOL_SEED_PATH,
	*,
	schools_per_province=DEMO_SCHOOLS_PER_PROVINCE,
	dry_run=True,
):
	"""Plan or apply removal of unselected canonical schools from the local demo.

	Only schools represented by the canonical source are candidates. Provinces,
wards, legacy schools, and schools outside that source remain untouched.
	Student and Contact links are protected so a prune cannot orphan business data.
	"""
	frappe.only_for("System Manager", True)
	if getattr(frappe.local, "site", None) != "crm.localhost" and not frappe.conf.get("allow_demo_seed"):
		frappe.throw("School demo pruning is restricted to crm.localhost.", frappe.PermissionError)
	full_report = reconcile_school_seed(path)
	selected_report = _demo_school_seed_report(full_report, schools_per_province)
	canonical_identities = {
		row["source_identity"]
		for row in full_report["rows"]
		if row.get("match_status") == "ready"
	}
	selected_identities = {row["source_identity"] for row in selected_report["rows"]}

	provinces = frappe.get_all(
		"CRM Province",
		fields=["name", "province_code"],
		limit_page_length=0,
	)
	province_codes = {row.name: row.province_code for row in provinces}
	wards = frappe.get_all(
		"CRM Ward",
		fields=["name", "province", "ward_code"],
		limit_page_length=0,
	)
	ward_codes = {(row.name, row.province): row.ward_code for row in wards}
	schools = frappe.get_all(
		"CRM High School",
		fields=["name", "province", "ward", "school_code"],
		limit_page_length=0,
	)
	candidate_names = []
	for school in schools:
		identity = source_identity(
			province_codes.get(school.province),
			ward_codes.get((school.ward, school.province)),
			school.school_code,
		)
		if identity in canonical_identities and identity not in selected_identities:
			candidate_names.append(school.name)

	def linked_names(doctype, field):
		if not candidate_names or not frappe.db.table_exists(doctype):
			return []
		return frappe.get_all(
			doctype,
			filters={field: ["in", candidate_names]},
			pluck="name",
			limit_page_length=0,
		)

	protected = {
		f"{doctype}.{field}": linked_names(doctype, field)
		for doctype, field in _SCHOOL_DOMAIN_PROTECTED_LINKS
	}
	protected = {key: names for key, names in protected.items() if names}
	child_counts = {
		f"{doctype}.{field}": len(linked_names(doctype, field))
		for doctype, field in _SCHOOL_DOMAIN_CHILD_LINKS
	}
	result = {
		"dry_run": dry_run,
		"source_ready_schools": len(canonical_identities),
		"selected_schools": len(selected_report["rows"]),
		"candidate_schools": len(candidate_names),
		"protected_links": {
			key: len(names)
			for key, names in protected.items()
		},
		"child_records": child_counts,
		"deleted": {},
		"demo_selection": selected_report["demo_selection"],
	}
	if dry_run:
		return result
	if candidate_names:
		prune_savepoint = "crm_school_seed_prune"
		frappe.db.savepoint(prune_savepoint)
		try:
			placeholders = ", ".join(["%s"] * len(candidate_names))
			frappe.db.sql(
				f"select name from `tabCRM High School` where name in ({placeholders}) for update",
				tuple(candidate_names),
			)
			# Re-check after locking the candidate parent rows. This keeps the
			# protected-link check and deletion in one transaction for local runs.
			protected = {
				f"{doctype}.{field}": linked_names(doctype, field)
				for doctype, field in _SCHOOL_DOMAIN_PROTECTED_LINKS
			}
			protected = {key: names for key, names in protected.items() if names}
			if protected:
				frappe.throw(
					"Cannot prune canonical schools while CRM Student or CRM Contact links remain: "
					+ ", ".join(f"{key}={len(names)}" for key, names in protected.items())
				)

			child_counts = {
				f"{doctype}.{field}": len(linked_names(doctype, field))
				for doctype, field in _SCHOOL_DOMAIN_CHILD_LINKS
			}
			result["child_records"] = child_counts
			for doctype, field in _SCHOOL_DOMAIN_CHILD_LINKS:
				if frappe.db.table_exists(doctype):
					frappe.db.delete(doctype, {field: ["in", candidate_names]})

			# A final guard prevents the parent delete if a protected link appeared
			# while child rows were being removed; rollback preserves the prior state.
			protected = {
				f"{doctype}.{field}": linked_names(doctype, field)
				for doctype, field in _SCHOOL_DOMAIN_PROTECTED_LINKS
			}
			protected = {key: names for key, names in protected.items() if names}
			if protected:
				frappe.throw(
					"Cannot prune canonical schools while CRM Student or CRM Contact links remain: "
					+ ", ".join(f"{key}={len(names)}" for key, names in protected.items())
				)
			frappe.db.delete("CRM High School", {"name": ["in", candidate_names]})
		except Exception:
			frappe.db.rollback(save_point=prune_savepoint)
			raise
	frappe.db.commit()
	result["deleted"] = {
		**child_counts,
		"CRM High School.name": len(candidate_names),
	}
	return result


def _import_snapshot(record, path):
	candidate = record["candidate"]
	data = record["data"]
	if record["source_sheet"] not in KEY_ACCOUNT_SOURCE_SHEETS:
		return 0
	created = 0
	for year in ANNUAL_YEARS:
		actual = _number(data.get(f"ne_{year}")) if year != 2026 else None
		target = _number(data.get("target_2026")) if year == 2026 else None
		if actual is None and target is None:
			continue
		admission_year = _ensure_admission_year(year)
		threshold = _number(data.get("adjusted_ne_threshold"))
		if threshold is None:
			threshold = 10
		values = {
			"high_school": candidate["name"],
			"admission_year": admission_year,
			"ne_target": target,
			"ne_actual": actual,
			"ne_actual_semantics": "New Enter History",
			"adjusted_ne_threshold": threshold,
			"verification_status": "Review Required",
		}
		_imported, _state = _upsert(
			"CRM High School Annual Snapshot",
			{"high_school": candidate["name"], "admission_year": admission_year},
			values,
		)
		created += 1
	return created


def _import_explicit_school_type(record):
	if record["source_sheet"] not in KEY_ACCOUNT_SOURCE_SHEETS:
		return False
	value = record["data"].get("school_type")
	if not value:
		return False
	term = _resolve_term("school_type", value)
	if not term:
		record.setdefault("reasons", []).append("unresolved_explicit_school_type")
		return False
	frappe.db.set_value("CRM High School", record["candidate"]["name"], "school_type", term, update_modified=False)
	return True


def _person_review_key(record):
	return f"{record.get('source_sheet', '')}:{record.get('source_row', '')}"


def _import_person(record, path, approved_person_rows=None):
	data = record["data"]
	if record["match_status"] != "matched" or not data.get("stakeholder_name"):
		return False
	record.setdefault("reasons", []).append("person_manual_review_required")
	review_key = _person_review_key(record)
	if hasattr(approved_person_rows, "get"):
		person_action = approved_person_rows.get(review_key)
	else:
		person_action = "create" if review_key in {str(value) for value in (approved_person_rows or ())} else None
	if not person_action:
		return False
	role = _resolve_term("stakeholder_role", data.get("stakeholder_role") or data.get("role"))
	if not role:
		record.setdefault("reasons", []).append("unresolved_stakeholder_role")
		return False
	staff, team = _resolve_ts_promoter_owner(None)
	if person_action == "create":
		# Explicit approval may create a new identity, but never silently merge it
		# into an existing Person based on name/phone/email.
		person = frappe.get_doc(
			{
				"doctype": "CRM Person",
				"full_name": data["stakeholder_name"],
				"phone": data.get("stakeholder_phone"),
				"email": data.get("stakeholder_email"),
			}
		).insert(ignore_permissions=True)
	else:
		if not frappe.db.exists("CRM Person", person_action):
			record.setdefault("reasons", []).append("approved_person_target_not_found")
			return False
		person = frappe.get_doc("CRM Person", person_action)
	record["approved_person"] = person.name
	association, _association_status = _upsert(
		"CRM School Stakeholder",
		{"high_school": record["candidate"]["name"], "person": person.name},
		{
			"high_school": record["candidate"]["name"],
			"person": person.name,
			"stakeholder_role": role,
			"position_title": data.get("position_title") or data.get("role"),
			"owner_staff": staff,
			"owning_team": team,
		},
	)
	record["stakeholder_association"] = association.name
	return True


def _import_activity(record, path):
	data = record["data"]
	if record["import_kind"] != "activity" or record["match_status"] != "matched":
		return False
	activity_type = _resolve_term("activity_type", data.get("activity_type"))
	activity_date = _date_value(data.get("activity_date"))
	if not activity_type or not activity_date:
		record.setdefault("reasons", []).append("activity_type_or_date_missing")
		return False
	staff, team = _resolve_ts_promoter_owner(None)
	year = _number(data.get("admission_year"))
	values = {
		"high_school": record["candidate"]["name"],
		"stakeholder": record.get("stakeholder_association"),
		"admission_year": _ensure_admission_year(year) if year else None,
		"activity_type": activity_type,
		"activity_date": activity_date,
		"owner_staff": staff,
		"owning_team": team,
		"status": data.get("status") if data.get("status") in {"Planned", "Completed", "Cancelled"} else "Planned",
		"outcome": data.get("outcome"),
	}
	values["import_idempotency_key"] = _activity_import_key(path, record, values)
	_upsert(
		"CRM School Activity",
		{"import_idempotency_key": values["import_idempotency_key"]},
		values,
	)
	return True


def _activity_import_key(path, record, values):
	return hashlib.sha256(
		"|".join(str(value or "") for value in (
			_source_file_name(path), record.get("source_sheet"), record.get("source_row"),
			values.get("high_school"), values.get("activity_date"), values.get("activity_type"),
			values.get("owner_staff"), values.get("owning_team"),
		)).encode("utf-8")
	).hexdigest()


def seed_ts_workbook(
	path=DEFAULT_TS_PATH,
	*,
	canonical_path=DEFAULT_SCHOOL_SEED_PATH,
	dry_run=True,
	approved_person_rows=None,
	commit_policy="partial",
):
	"""Apply TS data after school matching and explicit Person approval.

	``approved_person_rows`` accepts either review keys (which explicitly mean
	``create``) or a mapping of review key to an existing CRM Person name. The
	returned ``person_approval_targets`` lets a rerun switch a created row to its
	explicit Person ID without any implicit contact-based merge.
	"""
	if commit_policy not in {"partial", "all"}:
		frappe.throw("commit_policy must be 'partial' or 'all'.")
	report = reconcile_ts_workbook(path, canonical_path=canonical_path)
	if dry_run:
		return {"dry_run": True, "report": _public_reconciliation_report(report), "mutations": {}, "commit_policy": commit_policy}
	frappe.only_for("System Manager", True)
	preflight_issues = _ts_owner_preflight(report["rows"])
	if preflight_issues:
		return {
			"dry_run": False,
			"report": report,
			"mutations": {},
			"errors": preflight_issues,
			"preflight": "failed",
			"commit_policy": commit_policy,
		}
	counts = Counter()
	person_approval_targets = {}
	errors = []
	for record in report["rows"]:
		if _blocking_review(record):
			counts["review_required"] += 1
			continue
		savepoint = f"crm_ts_seed_{record['source_row']}"
		frappe.db.savepoint(savepoint)
		try:
			candidate = record["candidate"]
			candidate["name"] = frappe.db.get_value("CRM High School", _school_db_filters(candidate), "name")
			if not candidate["name"]:
				counts["review_required"] += 1
				record.setdefault("reasons", []).append("canonical_school_not_seeded")
				continue
			if _import_explicit_school_type(record):
				counts["school_types"] += 1
			if _import_snapshot(record, path):
				counts["annual_snapshots"] += 1
			if _import_person(record, path, approved_person_rows):
				counts["persons"] += 1
				person_approval_targets[_person_review_key(record)] = record["approved_person"]
			elif "person_manual_review_required" in record.get("reasons", []):
				counts["person_review_required"] += 1
			if _import_activity(record, path):
				counts["activities"] += 1
		except Exception as exc:
			frappe.db.rollback(save_point=savepoint)
			counts["errors"] += 1
			errors.append({"source_sheet": record["source_sheet"], "source_row": record["source_row"], "message": str(exc)})
	canonical = reconcile_school_seed(canonical_path)["rows"]
	_by_name, _by_global_name, by_identity = _school_index(canonical)
	supplement = _load_ne_2026_supplement(path)
	grouped = defaultdict(lambda: {"ne_2026": 0, "rows": []})
	for record in report.get("_ne_2026_rows", []):
		if _blocking_review(record):
			counts["review_required"] += 1
			continue
		value = _number(record.get("ne_2026"))
		if value is None:
			counts["review_required"] += 1
			continue
		grouped[record["canonical_source_identity"]]["ne_2026"] += value
		grouped[record["canonical_source_identity"]]["rows"].append(record["source_row"])
	for identity, payload in grouped.items():
		candidate = by_identity[identity]
		candidate["name"] = frappe.db.get_value("CRM High School", _school_db_filters(candidate), "name")
		if not candidate["name"]:
			counts["review_required"] += 1
			continue
		savepoint = f"crm_ne_2026_{min(payload['rows'])}"
		frappe.db.savepoint(savepoint)
		try:
			_upsert(
				"CRM High School Annual Snapshot",
				{"high_school": candidate["name"], "admission_year": _ensure_admission_year(2026)},
				{
					"high_school": candidate["name"],
					"admission_year": _ensure_admission_year(2026),
					"ne_actual": payload["ne_2026"],
					"ne_actual_semantics": "New Enter History",
					"verification_status": "Review Required",
				},
			)
			counts["annual_snapshots"] += 1
		except Exception as exc:
			frappe.db.rollback(save_point=savepoint)
			counts["errors"] += 1
			errors.append({"source_sheet": supplement["source_sheet"], "source_row": min(payload["rows"]), "message": str(exc)})
	if commit_policy == "all" and errors:
		frappe.db.rollback()
		return {
			"dry_run": False,
			"report": report,
			"mutations": {},
			"errors": errors,
			"commit_policy": commit_policy,
		}
	frappe.db.commit()
	mutations = dict(counts)
	if person_approval_targets:
		mutations["person_approval_targets"] = person_approval_targets
	return {
		"dry_run": False,
		"report": report,
		"mutations": mutations,
		"errors": errors,
		"commit_policy": commit_policy,
	}
