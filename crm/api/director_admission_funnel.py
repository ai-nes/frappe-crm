"""Aggregate snapshot API for the Director admission funnel.

The endpoint deliberately returns only aggregate data.  It is whitelisted for
guest-facing dashboard shells, and no student identity or row-level detail may
be added to this module.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

import frappe
from frappe import _

LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
QUERY_PAGE_SIZE = 5_000
COHORT_HORIZON_WEEKS = (1, 2, 3, 4, 5, 6)
MAX_COHORT_ROWS = 6
MAX_SOURCE_PERFORMANCE_ROWS = 10

STAGE_ORDER = (
	"prospect",
	"engaged",
	"qualified",
	"counselling",
	"application",
	"accepted",
	"enrolled",
)
STAGE_LABELS = {
	"prospect": "Hồ sơ tiềm năng",
	"engaged": "Đã tương tác",
	"qualified": "Đủ điều kiện",
	"counselling": "Đã tư vấn",
	"application": "Đã đăng ký",
	"accepted": "Đã trúng tuyển",
	"enrolled": "Đã nhập học",
}
STAGE_DESCRIPTIONS = {
	"prospect": "Có định danh và đồng ý nhận tư vấn",
	"engaged": "Đã phản hồi hai chiều",
	"qualified": "Đúng nhóm tuyển sinh mục tiêu",
	"counselling": "Đã có ít nhất một phiên tư vấn",
	"application": "Đã khởi tạo hồ sơ đăng ký",
	"accepted": "Đủ điều kiện nhập học",
	"enrolled": "Đã hoàn tất xác nhận nhập học",
}
LIFECYCLE_TO_STAGE = {
	"lead": "prospect",
	"mql": "qualified",
	"applicant": "application",
	"enrolled": "enrolled",
	"lost": "lost",
}
STATUS_TO_STAGE = {
	"moi": "prospect",
	"lead moi": "prospect",
	"moi nhan": "prospect",
	"da lien he": "engaged",
	"da tuong tac": "engaged",
	"co trien vong": "qualified",
	"dang tu van": "counselling",
	"da tu van": "counselling",
	"da nop ho so": "application",
	"da dang ky": "application",
	"da xac nhan": "application",
	"da trung tuyen": "accepted",
	"da nhap hoc": "enrolled",
	"da chuyen doi": "enrolled",
	"khong quan tam": "lost",
	"sai so": "lost",
	"sai doi tuong": "lost",
	"tu choi": "lost",
	# CRM Enrollment Status codes (post CRM Term cutover) -- enrollment_status
	# now stores the UPPER_SNAKE code, not the Vietnamese display label above.
	"new": "prospect",
	"prospect": "qualified",
	"confirmed": "application",
	"enrolled": "enrolled",
	"converted": "enrolled",
	"refused": "lost",
}
APPLICATION_TO_STAGE = {
	"submitted": "application",
	"under review": "application",
	"accepted": "accepted",
	"enrolled": "enrolled",
	"lost": "lost",
	"withdrawn": "lost",
}
LIFECYCLE_EVENT_TO_STAGE = {
	"lead": "prospect",
	"mql": "qualified",
	"applicant": "application",
	"enrolled": "enrolled",
}

STUDENT_FIELDS = [
	"name",
	"admission_year",
	"lifecycle_stage",
	"enrollment_status",
	"branch",
	"province",
	"ward",
	"source",
	"advertising_channel",
	"creation",
	"modified",
	"enrollment_date",
]
APPLICATION_FIELDS = [
	"name",
	"student",
	"status",
	"submitted_at",
	"enrolled_at",
	"modified",
	"campus",
]
INTERACTION_FIELDS = ["name", "student", "interaction_datetime"]
LIFECYCLE_EVENT_FIELDS = ["name", "student", "to_stage", "occurred_at"]
SOURCE_FIELDS = ["name", "source_name", "channel_family", "approval_state"]


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_director_admission_funnel(
	admissionYear: str | int | None = None,
	scope: str = "all",
) -> dict[str, Any]:
	"""Return one consistent aggregate snapshot for ``/director/admission-funnel``."""
	admission_year = _resolve_admission_year(admissionYear)
	scope_context = _normalize_scope(scope)
	_authorize_scope(scope_context)
	as_of = _now()
	warnings: list[str] = []
	records = _load_snapshot_records(admission_year, scope_context, as_of, warnings)
	source_rows = _load_sources(warnings)

	stages = _build_stages(records)
	drop_offs = _build_drop_offs(stages)
	aging = _build_aging(records, as_of)
	cohorts = _build_cohorts(records, as_of)
	source_performance = _build_source_performance(records, source_rows)
	summary = _build_summary(records, stages, drop_offs)
	priority_actions = _build_priority_actions(summary, aging, source_performance)

	return {
		"meta": {
			"admissionYear": _year_number(admission_year),
			"scope": scope_context["id"],
			"scopeLabel": scope_context["label"],
			"asOf": _as_iso(as_of),
			"timezone": "Asia/Ho_Chi_Minh",
			"status": "partial" if warnings else "available",
			**({"warnings": _unique(warnings)} if warnings else {}),
		},
		"summary": summary,
		"stages": stages,
		"dropOffs": drop_offs,
		"aging": aging,
		"sourcePerformance": source_performance,
		"cohorts": cohorts,
		"priorityActions": priority_actions,
	}


def _resolve_admission_year(value: Any = None) -> str:
	parsed = _parse_admission_year(value)
	if parsed:
		rows = _fetch_rows(
			"CRM Admission Year",
			filters={"name": parsed},
			fields=["name", "year_name"],
			order_by="name asc",
			allow_missing=False,
		)
		if not rows:
			rows = _fetch_rows(
				"CRM Admission Year",
				filters={"year_name": parsed},
				fields=["name", "year_name"],
				order_by="name asc",
				allow_missing=False,
			)
		if not rows:
			_raise_api_error(
				"ADMISSION_YEAR_NOT_FOUND",
				"Không tồn tại dữ liệu cho kỳ tuyển sinh được yêu cầu.",
				getattr(frappe, "DoesNotExistError", frappe.ValidationError),
				404,
			)
		return str(rows[0].get("name") or parsed)

	rows = _fetch_rows(
		"CRM Admission Year",
		filters={"is_active": 1},
		fields=["name", "year_name"],
		order_by="year_name desc, name desc",
		limit=2,
		allow_missing=False,
	)
	if len(rows) != 1:
		_raise_api_error(
			"INVALID_ADMISSION_YEAR",
			"Cần có đúng một kỳ tuyển sinh đang hoạt động.",
			frappe.ValidationError,
			422,
		)
	return str(rows[0].get("name") or rows[0].get("year_name"))


def _parse_admission_year(value: Any) -> str | None:
	if value is None or str(value).strip() == "":
		return None
	text = str(value).strip()
	if not re.fullmatch(r"\d{4}", text) or not 2000 <= int(text) <= 2100:
		_raise_api_error(
			"INVALID_ADMISSION_YEAR",
			"Kỳ tuyển sinh phải là năm 4 chữ số trong khoảng 2000..2100.",
			frappe.ValidationError,
			422,
		)
	return text


def _normalize_scope(value: Any = "all") -> dict[str, Any]:
	text = str(value or "all").strip()
	if not text or len(text) > 64 or any(ord(char) < 32 for char in text):
		_raise_api_error("INVALID_QUERY", "Tham số scope không hợp lệ.", frappe.ValidationError, 400)
	if text.casefold() == "all":
		return {"id": "all", "label": "Toàn bộ cơ sở", "branch": None, "territory": None}

	campus_rows = _fetch_rows(
		"CRM Campus",
		filters={"name": text},
		fields=["name", "campus_name", "campus_code"],
		order_by="name asc",
		allow_missing=True,
		limit=1,
	)
	if not campus_rows:
		campus_rows = _fetch_rows(
			"CRM Campus",
			filters={"campus_code": text},
			fields=["name", "campus_name", "campus_code"],
			order_by="name asc",
			allow_missing=True,
			limit=1,
		)
	if campus_rows:
		campus = campus_rows[0]
		return {
			"id": campus.get("name") or text,
			"label": campus.get("campus_name") or campus.get("name") or text,
			"branch": campus.get("name") or text,
			"territory": None,
		}

	territory_rows = _fetch_rows(
		"CRM Territory",
		filters={"name": text},
		fields=["name", "territory_name", "territory_code", "region"],
		order_by="name asc",
		allow_missing=True,
		limit=1,
	)
	if not territory_rows:
		territory_rows = _fetch_rows(
			"CRM Territory",
			filters={"territory_code": text},
			fields=["name", "territory_name", "territory_code", "region"],
			order_by="name asc",
			allow_missing=True,
			limit=1,
		)
	if territory_rows:
		territory = territory_rows[0]
		return {
			"id": territory.get("name") or text,
			"label": territory.get("territory_name") or territory.get("name") or text,
			"branch": None,
			"territory": territory.get("name") or text,
			"region": territory.get("region"),
		}

	_raise_api_error(
		"INVALID_QUERY", "Scope không tồn tại hoặc không được hỗ trợ.", frappe.ValidationError, 400
	)
	return {}


def _authorize_scope(scope: dict[str, Any]) -> None:
	"""Allow the guest shell to request only the public all-campus aggregate.

	Authenticated callers must be a Director/System Manager and may not use a
	campus outside their assigned CRM Staff scope.  This keeps ``allow_guest``
	compatible with the public shell without allowing the query string to choose
	an arbitrary restricted slice.
	"""
	user = getattr(getattr(frappe, "session", None), "user", None)
	if not user or user == "Guest":
		if scope.get("id") != "all":
			_raise_api_error(
				"FORBIDDEN",
				"Guest chỉ được truy cập snapshot toàn bộ cơ sở.",
				frappe.PermissionError,
				403,
			)
		return

	from crm.api.director_school_common import require_director_access

	access = require_director_access()
	if scope.get("id") == "all" or user == "Administrator" or access.get("roleState") == "system_manager":
		return

	staff_campus = frappe.db.get_value("CRM Staff", {"user": user, "is_active": 1}, "campus")
	if not scope.get("branch") or not staff_campus or scope["branch"] != staff_campus:
		_raise_api_error(
			"FORBIDDEN",
			"Scope không nằm trong phạm vi được cấp quyền.",
			frappe.PermissionError,
			403,
		)


def _load_snapshot_records(
	admission_year: str,
	scope: dict[str, Any],
	as_of: datetime | None = None,
	warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
	warnings = warnings if warnings is not None else []
	students = _load_students(admission_year, scope)
	lookups = _load_lookups(students, warnings)
	if scope.get("territory"):
		assignments = _load_territory_geographies(scope["territory"], as_of or _now())
		scope = {**scope, "territory_geographies": assignments}
		students = _filter_students_by_territory(students, scope, lookups)

	student_ids = {row.get("name") for row in students if row.get("name")}
	applications = _load_applications(admission_year, scope, warnings)
	applications = [row for row in applications if row.get("student") in student_ids]
	interactions = _load_interactions(student_ids, warnings)
	lifecycle_events = _load_lifecycle_events(student_ids, warnings)
	return _build_records(students, applications, interactions, lifecycle_events, lookups.get("sources", {}))


def _load_students(admission_year: str, scope: dict[str, Any]) -> list[dict[str, Any]]:
	filters: dict[str, Any] = {"admission_year": admission_year}
	if scope.get("branch"):
		filters["branch"] = scope["branch"]
	return _fetch_rows(
		"CRM Student",
		filters=filters,
		fields=STUDENT_FIELDS,
		order_by="creation asc, name asc",
		allow_missing=False,
	)


def _load_applications(
	admission_year: str, scope: dict[str, Any], warnings: list[str]
) -> list[dict[str, Any]]:
	if not _table_exists("CRM Admission Application"):
		warnings.append("CRM Admission Application không khả dụng; source application metrics có thể thiếu.")
		return []
	filters: dict[str, Any] = {"admission_year": admission_year}
	if scope.get("branch"):
		filters["campus"] = scope["branch"]
	return _fetch_rows(
		"CRM Admission Application",
		filters=filters,
		fields=APPLICATION_FIELDS,
		order_by="modified asc, name asc",
		allow_missing=False,
	)


def _load_interactions(student_ids: set[str], warnings: list[str]) -> list[dict[str, Any]]:
	if not student_ids:
		return []
	if not _table_exists("CRM Interaction"):
		warnings.append("CRM Interaction không khả dụng; bước tương tác được suy ra từ hồ sơ hiện có.")
		return []
	return _fetch_rows(
		"CRM Interaction",
		filters={"student": ["in", list(student_ids)]},
		fields=INTERACTION_FIELDS,
		order_by="interaction_datetime asc, name asc",
		allow_missing=False,
	)


def _load_lifecycle_events(student_ids: set[str], warnings: list[str]) -> list[dict[str, Any]]:
	if not student_ids:
		return []
	if not _table_exists("CRM Student Lifecycle Event"):
		warnings.append("Lifecycle event chưa khả dụng; aging dùng thời điểm sửa hồ sơ làm dự phòng.")
		return []
	return _fetch_rows(
		"CRM Student Lifecycle Event",
		filters={"student": ["in", list(student_ids)]},
		fields=LIFECYCLE_EVENT_FIELDS,
		order_by="occurred_at asc, name asc",
		allow_missing=False,
	)


def _load_sources(warnings: list[str]) -> list[dict[str, Any]]:
	if not _table_exists("CRM Lead Source"):
		warnings.append("CRM Lead Source chưa khả dụng; nguồn chỉ hiển thị theo dữ liệu hồ sơ.")
		return []
	try:
		return _fetch_rows(
			"CRM Lead Source",
			filters={},
			fields=SOURCE_FIELDS,
			order_by="source_name asc, name asc",
			allow_missing=False,
		)
	except Exception:
		warnings.append("Không thể tải danh mục nguồn tuyển sinh.")
		return []


def _load_lookups(students: list[dict[str, Any]], warnings: list[str]) -> dict[str, dict[str, Any]]:
	province_ids = {row.get("province") for row in students if row.get("province")}
	source_ids = {row.get("source") for row in students if row.get("source")}
	lookups: dict[str, dict[str, Any]] = {"provinces": {}, "sources": {}}
	if province_ids and _table_exists("CRM Province"):
		try:
			rows = _fetch_rows(
				"CRM Province",
				filters={"name": ["in", list(province_ids)]},
				fields=["name", "province_name", "province_code", "region"],
				order_by="name asc",
				allow_missing=False,
			)
			lookups["provinces"] = {row.get("name"): dict(row) for row in rows if row.get("name")}
		except Exception:
			warnings.append("Không thể tải danh mục tỉnh/thành để áp dụng scope territory.")
	if _table_exists("CRM Lead Source"):
		try:
			rows = _fetch_rows(
				"CRM Lead Source",
				filters={"name": ["in", list(source_ids)]} if source_ids else {},
				fields=SOURCE_FIELDS,
				order_by="source_name asc, name asc",
				allow_missing=False,
			)
			lookups["sources"] = {
				row.get("name"): {
					"id": row.get("name"),
					"label": row.get("source_name") or row.get("channel_family") or row.get("name"),
				}
				for row in rows
				if row.get("name")
			}
		except Exception:
			warnings.append("Không thể tải danh mục nguồn tuyển sinh cho snapshot.")
	return lookups


def _load_territory_geographies(territory: str, as_of: datetime) -> list[dict[str, Any]]:
	if not _table_exists("CRM Territory Geography Assignment"):
		_raise_api_error(
			"DIRECTOR_ADMISSION_FUNNEL_UNAVAILABLE",
			"Không thể xác định phạm vi địa lý của territory.",
			frappe.ValidationError,
			503,
		)
	rows = _fetch_rows(
		"CRM Territory Geography Assignment",
		filters={"territory": territory, "status": "Active"},
		fields=["geography_type", "geography", "effective_from", "effective_until"],
		order_by="effective_from desc, name desc",
		allow_missing=False,
	)
	current = [row for row in rows if _assignment_is_current(row, as_of)]
	if not current:
		_raise_api_error(
			"FORBIDDEN",
			"Territory chưa có phạm vi địa lý đang hiệu lực.",
			frappe.PermissionError,
			403,
		)
	return current


def _filter_students_by_territory(
	students: list[dict[str, Any]], scope: dict[str, Any], lookups: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
	assignments = scope.get("territory_geographies") or []
	return [
		row
		for row in students
		if any(_student_matches_geography(row, assignment, lookups) for assignment in assignments)
	]


def _student_matches_geography(
	student: dict[str, Any], assignment: dict[str, Any], lookups: dict[str, dict[str, Any]]
) -> bool:
	geography = _fold(assignment.get("geography"))
	geography_type = _fold(assignment.get("geography_type"))
	province = lookups.get("provinces", {}).get(student.get("province"), {})
	province_values = {
		_fold(student.get("province")),
		_fold(province.get("province_name")),
		_fold(province.get("province_code")),
	}
	if geography_type == "province":
		return geography in province_values
	if geography_type == "ward":
		return geography == _fold(student.get("ward"))
	if geography_type == "region":
		return geography == _fold(province.get("region"))
	return False


def _build_records(
	students: list[dict[str, Any]],
	applications: list[dict[str, Any]],
	interactions: list[dict[str, Any]] | None = None,
	lifecycle_events: list[dict[str, Any]] | None = None,
	source_lookup: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
	applications_by_student: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for application in applications:
		if application.get("student"):
			applications_by_student[application["student"]].append(application)

	interactions_by_student: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for interaction in interactions or []:
		if interaction.get("student"):
			interactions_by_student[interaction["student"]].append(interaction)

	events_by_student: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for event in lifecycle_events or []:
		if event.get("student"):
			events_by_student[event["student"]].append(event)

	records = []
	for row in students:
		student_id = row.get("name")
		if not student_id:
			continue
		stage_times: dict[str, list[datetime]] = defaultdict(list)
		created_at = _coerce_datetime(row.get("creation"))
		modified_at = _coerce_datetime(row.get("modified"))
		if created_at:
			stage_times["prospect"].append(created_at)

		stages: set[str] = set()
		status_stage = STATUS_TO_STAGE.get(_fold(row.get("enrollment_status")))
		lifecycle_stage = LIFECYCLE_TO_STAGE.get(_fold(row.get("lifecycle_stage")))
		if status_stage == "lost":
			status_stage = None
		if lifecycle_stage == "lost":
			lifecycle_stage = None
		if status_stage:
			stages.add(status_stage)
		if lifecycle_stage:
			stages.add(lifecycle_stage)

		for event in events_by_student.get(student_id, []):
			stage = LIFECYCLE_EVENT_TO_STAGE.get(_fold(event.get("to_stage")))
			when = _coerce_datetime(event.get("occurred_at"))
			if stage:
				stages.add(stage)
				if when:
					stage_times[stage].append(when)

		for interaction in interactions_by_student.get(student_id, []):
			stages.add("engaged")
			when = _coerce_datetime(interaction.get("interaction_datetime"))
			if when:
				stage_times["engaged"].append(when)

		applicant_at = None
		enrolled_at = _coerce_datetime(row.get("enrollment_date"))
		for application in applications_by_student.get(student_id, []):
			stage = APPLICATION_TO_STAGE.get(str(application.get("status") or "").strip().casefold())
			when = _coerce_datetime(application.get("modified"))
			if stage == "lost":
				continue
			if stage:
				stages.add(stage)
				if when:
					stage_times[stage].append(when)
			if application.get("submitted_at"):
				submitted_at = _coerce_datetime(application.get("submitted_at"))
				if submitted_at:
					applicant_at = min(filter(None, (applicant_at, submitted_at)), default=submitted_at)
					stage_times["application"].append(submitted_at)
			if application.get("enrolled_at"):
				application_enrolled_at = _coerce_datetime(application.get("enrolled_at"))
				if application_enrolled_at:
					enrolled_at = min(
						filter(None, (enrolled_at, application_enrolled_at)), default=application_enrolled_at
					)
					stage_times["enrolled"].append(application_enrolled_at)

		for stage in {status_stage, lifecycle_stage}:
			if stage and not stage_times.get(stage) and modified_at:
				stage_times[stage].append(modified_at)

		if not stages:
			if (
				_fold(row.get("enrollment_status"))
				in {
					"khong quan tam",
					"sai so",
					"sai doi tuong",
					"tu choi",
				}
				or _fold(row.get("lifecycle_stage")) == "lost"
			):
				continue
			stages.add("prospect")
		if not created_at:
			created_at = modified_at
		if not applicant_at:
			applicant_at = max(stage_times.get("application", []), default=None)

		last_stage = max(stages, key=lambda stage: STAGE_ORDER.index(stage))
		for stage in STAGE_ORDER[: STAGE_ORDER.index(last_stage) + 1]:
			if not stage_times.get(stage) and (modified_at or created_at):
				stage_times[stage].append(modified_at or created_at)
		entry_times = {
			stage: max(values).isoformat(timespec="seconds")
			for stage, values in stage_times.items()
			if values
		}
		source_id = row.get("source") or row.get("advertising_channel") or "unknown"
		source_info = (source_lookup or {}).get(row.get("source"), {})
		records.append(
			{
				"id": student_id,
				"stages": stages,
				"activeStage": last_stage,
				"stageEnteredAt": entry_times,
				"createdAt": _as_iso(created_at),
				"applicantAt": _as_iso(applicant_at),
				"enrolledAt": _as_iso(enrolled_at),
				"sourceId": source_id,
				"sourceLabel": source_info.get("label")
				or ("Chưa xác định" if source_id == "unknown" else source_id),
			}
		)
	return records


# Keep the name discoverable for callers that use the terminology from the
# Director overview module.
_build_student_records = _build_records


def _build_stages(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
	prospects = sum(_record_reached(record, "prospect") for record in records)
	result = []
	previous_count = None
	for index, stage in enumerate(STAGE_ORDER):
		count = sum(_record_reached(record, stage) for record in records)
		step_rate = 100.0 if index == 0 else _ratio(count, previous_count)
		result.append(
			{
				"id": stage,
				"label": STAGE_LABELS[stage],
				"description": STAGE_DESCRIPTIONS[stage],
				"count": count,
				"remainingRate": _ratio(count, prospects) or 0.0,
				"stepRate": step_rate,
			}
		)
		previous_count = count
	return result


def _build_drop_offs(stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
	items = []
	for index in range(1, len(stages)):
		before = stages[index - 1]
		after = stages[index]
		step_rate = after["stepRate"]
		drop_rate = round(100.0 - step_rate, 1) if step_rate is not None else 0.0
		items.append(
			{
				"fromStageId": before["id"],
				"toStageId": after["id"],
				"fromLabel": before["label"],
				"toLabel": after["label"],
				"dropCount": max(before["count"] - after["count"], 0),
				"dropRate": drop_rate,
				"_order": index,
			}
		)
	items.sort(key=lambda item: (-item["dropRate"], item["_order"]))
	for item in items:
		item.pop("_order", None)
	return items


def _build_summary(
	records: list[dict[str, Any]], stages: list[dict[str, Any]], drop_offs: list[dict[str, Any]]
) -> dict[str, Any]:
	prospects = stages[0]["count"] if stages else 0
	enrolled = stages[-1]["count"] if stages else 0
	priority = next((item for item in drop_offs if item["dropCount"] > 0), None)
	return {
		"prospects": prospects,
		"enrolled": enrolled,
		"enrollmentRate": _ratio(enrolled, prospects),
		"priorityStageId": priority["fromStageId"] if priority else None,
		"priorityNextStageId": priority["toStageId"] if priority else None,
		"priorityDropRate": priority["dropRate"] if priority else None,
		"priorityDropCount": priority["dropCount"] if priority else None,
	}


def _build_aging(records: list[dict[str, Any]], as_of: datetime) -> dict[str, Any]:
	buckets = {
		stage: {
			"underThreeDays": 0,
			"threeToSevenDays": 0,
			"sevenToFourteenDays": 0,
			"overFourteenDays": 0,
			"ages": [],
		}
		for stage in STAGE_ORDER[:-1]
	}
	for record in records:
		stage = _active_stage(record)
		if stage not in buckets:
			continue
		entered = _stage_entered_at(record, stage)
		if not entered:
			continue
		age_days = max((as_of - entered).total_seconds() / 86_400, 0.0)
		bucket = buckets[stage]
		bucket["ages"].append(age_days)
		if age_days < 3:
			bucket["underThreeDays"] += 1
		elif age_days < 7:
			bucket["threeToSevenDays"] += 1
		elif age_days <= 14:
			bucket["sevenToFourteenDays"] += 1
		else:
			bucket["overFourteenDays"] += 1

	rows = []
	for stage in STAGE_ORDER[:-1]:
		bucket = buckets[stage]
		rows.append(
			{
				"stageId": stage,
				"stage": STAGE_LABELS[stage],
				"underThreeDays": bucket["underThreeDays"],
				"threeToSevenDays": bucket["threeToSevenDays"],
				"sevenToFourteenDays": bucket["sevenToFourteenDays"],
				"overFourteenDays": bucket["overFourteenDays"],
				"medianDays": round(float(median(bucket["ages"])), 1) if bucket["ages"] else None,
			}
		)
	return {
		"totalOverFourteenDays": sum(row["overFourteenDays"] for row in rows),
		"rows": rows,
	}


def _build_source_performance(
	records: list[dict[str, Any]], source_rows: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
	"""Return the ten highest-volume sources for the compact Director card."""
	definitions: dict[str, str] = {}
	for row in source_rows or []:
		if row.get("approval_state") == "Retired":
			continue
		source_id = row.get("name") or row.get("id")
		if source_id:
			definitions[source_id] = (
				row.get("source_name") or row.get("label") or row.get("channel_family") or source_id
			)
	for record in records:
		source_id = _record_source_id(record)
		definitions.setdefault(source_id, record.get("sourceLabel") or source_id)

	items = []
	for source_id, label in definitions.items():
		matches = [record for record in records if _record_source_id(record) == source_id]
		counts = [sum(_record_reached(record, stage) for record in matches) for stage in STAGE_ORDER]
		items.append(
			{
				"id": source_id,
				"label": label,
				"stepRates": [_ratio(counts[index + 1], counts[index]) for index in range(6)],
				"finalRate": _ratio(counts[-1], counts[0]),
				"_prospectCount": counts[0],
			}
		)
	items.sort(
		key=lambda item: (
			-item["_prospectCount"],
			str(item["label"]).casefold(),
			str(item["id"]),
		)
	)
	return [
		{key: value for key, value in item.items() if key != "_prospectCount"}
		for item in items[:MAX_SOURCE_PERFORMANCE_ROWS]
	]


def _build_cohorts(records: list[dict[str, Any]], as_of: datetime) -> dict[str, Any]:
	grouped: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
	for record in records:
		created = _record_datetime(record, "createdAt", "created_at")
		if created:
			week_start = (created - timedelta(days=created.weekday())).replace(
				hour=0, minute=0, second=0, microsecond=0
			)
			grouped[week_start].append(record)

	weeks = sorted(grouped)[-MAX_COHORT_ROWS:]
	rows = []
	for week_start in weeks:
		cohort = grouped[week_start]
		values = []
		for weeks_after in COHORT_HORIZON_WEEKS:
			horizon = max(
				(_record_datetime(record, "createdAt", "created_at") or week_start)
				+ timedelta(weeks=weeks_after)
				for record in cohort
			)
			if as_of < horizon:
				values.append(None)
				continue
			reached = sum(
				_application_reached_by(
					record,
					(_record_datetime(record, "createdAt", "created_at") or week_start)
					+ timedelta(weeks=weeks_after),
				)
				for record in cohort
			)
			values.append(_ratio(reached, len(cohort)) or 0.0)
		rows.append(
			{
				"id": f"week-{week_start.date().isoformat()}",
				"label": f"Tuần {week_start.isocalendar().week}",
				"values": values,
			}
		)
	return {
		"targetStageId": "application",
		"followUpWeeks": list(COHORT_HORIZON_WEEKS),
		"completeCohortCount": sum(all(value is not None for value in row["values"]) for row in rows),
		"rows": rows,
	}


def _application_reached_by(record: dict[str, Any], deadline: datetime) -> bool:
	application_at = _record_datetime(record, "applicantAt", "applicant_at") or _stage_entered_at(
		record, "application"
	)
	return bool(application_at and application_at <= deadline)


def _build_priority_actions(
	summary: dict[str, Any], aging: dict[str, Any], source_performance: list[dict[str, Any]]
) -> list[dict[str, Any]]:
	actions = []
	if summary.get("priorityStageId"):
		from_label = STAGE_LABELS[summary["priorityStageId"]]
		to_label = STAGE_LABELS[summary["priorityNextStageId"]]
		actions.append(
			{
				"id": "improve-first-transition",
				"title": f"Cải thiện bước {from_label} → {to_label}",
				"detail": f"{_format_count(summary['priorityDropCount'])} hồ sơ chưa chuyển bước.",
				"tone": "error",
				"href": "/director/ai/next-best-action",
			}
		)
	if aging.get("totalOverFourteenDays", 0):
		actions.append(
			{
				"id": "clear-aging-backlog",
				"title": "Xử lý hồ sơ chờ trên 14 ngày",
				"detail": f"{_format_count(aging['totalOverFourteenDays'])} hồ sơ đang tồn đọng.",
				"tone": "warning",
				"href": "/director/students",
			}
		)
	best_source = max(
		(source for source in source_performance if source.get("finalRate") is not None),
		key=lambda source: (source["finalRate"], str(source["id"])),
		default=None,
	)
	if best_source:
		actions.append(
			{
				"id": "scale-best-source",
				"title": "Nhân rộng nguồn có tỷ lệ nhập học cao",
				"detail": f"{best_source['label']} đang đạt {best_source['finalRate']:.1f}% nhập học.",
				"tone": "success",
			}
		)
	return actions[:3]


def _record_reached(record: dict[str, Any], stage: str) -> bool:
	if stage not in STAGE_ORDER:
		return False
	stages = record.get("stages") or set()
	if isinstance(stages, str):
		stages = {stages}
	if any(candidate in STAGE_ORDER for candidate in stages):
		return max(
			STAGE_ORDER.index(candidate) for candidate in stages if candidate in STAGE_ORDER
		) >= STAGE_ORDER.index(stage)
	active = record.get("activeStage") or record.get("active_stage") or record.get("stage")
	return active in STAGE_ORDER and STAGE_ORDER.index(active) >= STAGE_ORDER.index(stage)


def _active_stage(record: dict[str, Any]) -> str | None:
	active = record.get("activeStage") or record.get("active_stage") or record.get("stage")
	if active in STAGE_ORDER:
		return active
	stages = record.get("stages") or set()
	valid = [stage for stage in stages if stage in STAGE_ORDER]
	return max(valid, key=STAGE_ORDER.index, default=None)


def _stage_entered_at(record: dict[str, Any], stage: str) -> datetime | None:
	values = record.get("stageEnteredAt") or record.get("stage_entered_at") or {}
	value = values.get(stage) if isinstance(values, dict) else None
	return _coerce_datetime(value)


def _record_source_id(record: dict[str, Any]) -> str:
	return str(record.get("sourceId") or record.get("source_id") or record.get("source") or "unknown")


def _record_datetime(record: dict[str, Any], *keys: str) -> datetime | None:
	for key in keys:
		value = _coerce_datetime(record.get(key))
		if value:
			return value
	return None


def _ratio(numerator: int | float, denominator: int | float | None) -> float | None:
	if not denominator:
		return None
	return round(float(numerator) / float(denominator) * 100, 1)


def _assignment_is_current(row: dict[str, Any], as_of: datetime) -> bool:
	start = _coerce_datetime(row.get("effective_from"))
	end = _coerce_datetime(row.get("effective_until"))
	return (not start or start <= as_of) and (not end or end >= as_of)


def _fetch_rows(
	doctype: str,
	*,
	filters: dict[str, Any],
	fields: list[str],
	order_by: str | None = None,
	limit: int | None = None,
	allow_missing: bool = False,
) -> list[dict[str, Any]]:
	if not _table_exists(doctype):
		if allow_missing:
			return []
		_raise_api_error(
			"DIRECTOR_ADMISSION_FUNNEL_UNAVAILABLE",
			"Không thể tải nguồn dữ liệu phễu tuyển sinh.",
			frappe.ValidationError,
			503,
		)
	rows: list[dict[str, Any]] = []
	page_size = min(limit or QUERY_PAGE_SIZE, QUERY_PAGE_SIZE)
	start = 0
	while True:
		query: dict[str, Any] = {
			"filters": filters,
			"fields": fields,
			"limit_start": start,
			"limit_page_length": page_size,
		}
		if order_by:
			query["order_by"] = order_by
		try:
			batch = frappe.get_all(doctype, **query)
		except Exception:
			if allow_missing:
				return []
			_raise_api_error(
				"DIRECTOR_ADMISSION_FUNNEL_UNAVAILABLE",
				"Không thể tải nguồn dữ liệu phễu tuyển sinh.",
				frappe.ValidationError,
				503,
			)
		rows.extend(dict(row) for row in batch)
		if len(batch) < page_size or (limit is not None and len(rows) >= limit):
			return rows[:limit] if limit is not None else rows
		start += len(batch)


def _table_exists(doctype: str) -> bool:
	try:
		return bool(frappe.db.table_exists(doctype))
	except (AttributeError, frappe.DoesNotExistError):
		return False


def _coerce_datetime(value: Any) -> datetime | None:
	if not value:
		return None
	try:
		parsed = frappe.utils.get_datetime(value)
		if parsed.tzinfo is None:
			return parsed.replace(tzinfo=LOCAL_TIMEZONE)
		return parsed.astimezone(LOCAL_TIMEZONE)
	except (AttributeError, TypeError, ValueError, OverflowError):
		return None


def _now() -> datetime:
	return _coerce_datetime(frappe.utils.now_datetime()) or datetime.now(LOCAL_TIMEZONE)


def _as_iso(value: Any) -> str | None:
	parsed = _coerce_datetime(value)
	return parsed.isoformat(timespec="seconds") if parsed else None


def _year_number(value: Any) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		try:
			return int(frappe.db.get_value("CRM Admission Year", value, "year_name"))
		except (TypeError, ValueError, AttributeError):
			return 0


def _fold(value: Any) -> str:
	text = unicodedata.normalize("NFKD", str(value or "").casefold())
	return "".join(char for char in text if not unicodedata.combining(char)).replace("đ", "d")


def _format_count(value: int | float) -> str:
	return f"{round(value):,}".replace(",", ".")


def _unique(values: list[str]) -> list[str]:
	return list(dict.fromkeys(value for value in values if value))


def _raise_api_error(code: str, message: str, exception: type[Exception], status: int) -> None:
	try:
		if getattr(frappe, "local", None) and isinstance(getattr(frappe.local, "response", None), dict):
			frappe.local.response["error"] = {"code": code, "message": message}
			frappe.local.response["http_status_code"] = status
	except (AttributeError, TypeError):
		pass
	frappe.throw(_(message), exception)
