"""Session-scoped read-only API projections for the student dashboard."""

from __future__ import annotations

import html
import json
import re
import unicodedata
from datetime import timedelta
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

import frappe
from frappe import _

from crm.fcrm.interaction_log import CHATWOOT_INTERACTION_TYPE
from crm.fcrm.interaction_semantics import resolve_interaction_type
from crm.fcrm.permissions import (
	can_read_full_lead_board,
	get_student_list_read_condition,
	has_student_dashboard_read_permission,
)
from crm.fcrm.student_reference import (
	canonical_student,
	hs_code_for_reference,
	lead_for_reference,
	lead_for_student,
)
from crm.fcrm.student_stage import STUDENT_STAGES
from crm.integrations.api import get_recording_url_path

LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
ACTIVE_ACTION_STATES = ("pending", "accepted", "in-progress", "requires-review")
ASSIGNMENT_STATUSES = {
	"assigned": {"label": "Đã phân công"},
	"unassigned": {"label": "Chưa phân công"},
}
LIFECYCLE_STATUSES = {stage: {"label": stage} for stage in STUDENT_STAGES}
LIFECYCLE_STATUS_ALIASES = {
	"Lead": "New",
	"MQL": "Attempting",
	"Applicant": "Qualified",
	"Enrolled": "Connected",
	"Lost": "Disqualified",
}
# Keep the canonical Chatwoot type and the legacy seeded type readable while
# older CRM Interaction rows are being migrated to the canonical vocabulary.
CHATWOOT_INTERACTION_TYPES = (CHATWOOT_INTERACTION_TYPE, "TIN_NHAN_CHATWOOT")
_TRANSCRIPT_BLOCK_RE = re.compile(r"\[TRANSCRIPT\](.*?)\[/TRANSCRIPT\]", re.IGNORECASE | re.DOTALL)
_SUMMARY_BLOCK_RE = re.compile(
	r"\[AI_CALL_SUMMARY_V1\](.*?)\[/AI_CALL_SUMMARY_V1\]",
	re.IGNORECASE | re.DOTALL,
)
_DISPLAY_CODE_RE = re.compile(r"HS-(?P<year>\d{4})-HCM-(?P<sequence>\d{6})$", re.IGNORECASE)

STAGES = {
	"interested": {"label": "Quan tâm", "student_stage": "New"},
	"exploring": {"label": "Tìm hiểu", "student_stage": "Attempting"},
	"counselling": {"label": "Tư vấn", "student_stage": "Attempting"},
	"applying": {"label": "Ứng tuyển", "student_stage": "Qualified"},
	"enrolled": {"label": "Nhập học", "student_stage": "Connected"},
}
STAGE_BY_STUDENT_STAGE = {
	"New": {"code": "interested", "label": "Quan tâm"},
	"Attempting": {"code": "counselling", "label": "Tư vấn"},
	"Qualified": {"code": "applying", "label": "Ứng tuyển"},
	"Connected": {"code": "enrolled", "label": "Nhập học"},
}
PRIORITIES = {
	"high": {"label": "Cao", "rank": 1},
	"medium": {"label": "Trung bình", "rank": 2},
	"low": {"label": "Thấp", "rank": 3},
}
PRIORITY_THRESHOLD = 70
JOURNEY_MILESTONE_EVIDENCE_KINDS = frozenset(
	{"application_event", "document_event", "lifecycle_event", "payment_event"}
)
JOURNEY_EXCLUDED_ACTIVITY_TYPES = frozenset(
	{"note", "message", "message chatwoot", "message_chatwoot", "tin nhan chatwoot"}
)
JOURNEY_MILESTONE_TERMS = (
	"nop ho so",
	"hoan tat ho so",
	"ho so xet tuyen",
	"nhap hoc",
	"enrolled",
	"application",
	"submitted",
	"stage changed",
	"stage change",
	"chuyen giai doan",
	"doi stage",
	"thanh toan",
	"payment",
)
ASSESSMENT_FIELDS = [
	"status",
	"assessment_source",
	"assessed_at",
	"signal_score",
	"enrollment_probability",
	"interest",
	"interest_confidence",
	"fit",
	"fit_confidence",
	"primary_barrier",
	"barrier_confidence",
	"reason",
	"recommendation",
]
SORT_FIELDS = {
	"score": "latest_score",
	"priority": "modified",
	"lastActivityAt": "modified",
	"nextActionDueAt": "modified",
}
STUDENT_STAGE_ORDER = (
	"CASE student_stage "
	+ " ".join(f"WHEN '{stage}' THEN {rank}" for rank, stage in enumerate(STUDENT_STAGES, start=1))
	+ " ELSE 99 END"
)
STUDENT_STAGE_RANK = {stage: rank for rank, stage in enumerate(STUDENT_STAGES, start=1)}
STUDENT_FIELDS = [
	"name",
	"full_name",
	"lead_code",
	"source_lead",
	"campaign",
	"phone",
	"email",
	"gender",
	"date_of_birth",
	"student_identity",
	"student_context_revision",
	"high_school",
	"province",
	"major",
	"student_stage",
	"latest_score",
	"assessment_status",
	"interest_level",
	"fit_level",
	"primary_barrier",
	"current_grade",
	"study_stage",
	"graduation_score",
	"transcript_score",
	"english_converted_score",
	"total_score",
	"source",
	"aspiration",
	"branch",
	"ward",
	"notes",
	"owner_staff",
	"assigned_to",
	"admission_year",
	"modified",
	"privacy_status",
]


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_director_students(
	admissionYear: str | int | None = None,
	page: str | int = 1,
	pageSize: str | int = 20,
	q: str | None = "",
	stage: str | None = None,
	province: str | None = None,
	ownerId: str | None = None,
	sort: str = "score",
	order: str = "desc",
	assignmentStatus: str | None = None,
	lifecycleStatus: str | None = None,
	provinceId: str | None = None,
	assignment_status: str | None = None,
	lifecycle_status: str | None = None,
	province_id: str | None = None,
) -> dict[str, Any]:
	"""Return the session-scoped list/KPI envelope consumed by ``/director/students``.

	The dotted Frappe method is the canonical backend route. A gateway can map
	``GET /api/students`` to this method without changing the response contract.
	Student row visibility is enforced by the current session's CRM permissions.
	"""
	_require_access()
	query = _parse_query(
		admissionYear=admissionYear,
		page=page,
		pageSize=pageSize,
		q=q,
		stage=stage,
		province=province,
		ownerId=ownerId,
		sort=sort,
		order=order,
		assignmentStatus=assignmentStatus,
		lifecycleStatus=lifecycleStatus,
		provinceId=provinceId,
		assignment_status=assignment_status,
		lifecycle_status=lifecycle_status,
		province_id=province_id,
	)
	query["admission_year"] = _resolve_admission_year(query["admission_year"])
	resolved_province = _resolve_province(query["province"]) if query["province"] else None
	student_filters, or_filters = _student_filters(query, resolved_province)

	# CRM Lead remains the routing projection for this list. This keeps the
	# Student view aligned with the same active Group/Team/pool scope as Lead.
	list_scope_student_ids = _list_scope_student_ids()
	total = _count_students(
		student_filters,
		or_filters,
		allowed_student_ids=list_scope_student_ids,
	)
	total_all_filters = _canonical_student_filters(query["admission_year"])
	total_all = _count_students(total_all_filters, allowed_student_ids=list_scope_student_ids)
	rows = _fetch_student_rows(
		query,
		student_filters,
		or_filters,
		allowed_student_ids=list_scope_student_ids,
	)
	snapshot = _as_iso(frappe.utils.now_datetime())

	return {
		"data": _hydrate_rows(rows, sort_field=query["sort"]),
		"summary": _build_summary(
			query["admission_year"], allowed_student_ids=list_scope_student_ids
		),
		"actionSummary": _build_action_summary(
			query["admission_year"], allowed_student_ids=list_scope_student_ids
		),
		"meta": {
			"total": total,
			"totalAll": total_all,
			"page": query["page"],
			"pageSize": query["page_size"],
			"totalPages": _total_pages(total, query["page_size"]),
			"hasNextPage": query["page"] < _total_pages(total, query["page_size"]),
			"admissionYear": int(query["admission_year"]),
			"query": query["query"],
			"filters": {
				"stage": STAGES[query["stage"]]["label"] if query["stage"] else None,
				"assignmentStatus": query["assignment_status"],
				"lifecycleStatus": query["lifecycle_status"],
				"province": _province_label(resolved_province),
			},
			"sort": {"field": query["sort"], "order": query["order"]},
			"asOf": snapshot,
		},
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_director_student(student_id: str) -> dict[str, Any]:
	"""Return one permission-checked canonical CRM Student projection."""
	_require_access()
	student_id = _resolve_student_id(student_id)
	if not student_id:
		_raise_api_error("INVALID_STUDENT_ID", "studentId không được để trống.", frappe.ValidationError, 400)
	student_id = canonical_student(student_id) or student_id

	try:
		doc = frappe.get_doc("CRM Student", student_id)
	except frappe.DoesNotExistError:
		_raise_api_error("STUDENT_NOT_FOUND", "Không tìm thấy hồ sơ học sinh.", frappe.DoesNotExistError, 404)

	if not has_student_dashboard_read_permission(doc):
		_raise_api_error("STUDENT_NOT_FOUND", "Không tìm thấy hồ sơ học sinh.", frappe.DoesNotExistError, 404)

	row = _normalize_student_row(frappe._dict({field: doc.get(field) for field in STUDENT_FIELDS}))
	item = _hydrate_rows([row])[0]
	return _build_student_360(row, item)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_student_interactions(student_id: str) -> dict[str, Any]:
	"""Return interaction history (Zalo messages and Call Logs) for a CRM Student."""
	_require_access()
	requested_id, activity_id, canonical_id = _resolve_activity_target(student_id)
	if not requested_id:
		_raise_api_error("INVALID_STUDENT_ID", "studentId không được để trống.", frappe.ValidationError, 400)

	try:
		doc = frappe.get_doc("CRM Lead", activity_id)
	except frappe.DoesNotExistError:
		canonical_id = canonical_id or canonical_student(activity_id)
		if not canonical_id:
			_raise_api_error("STUDENT_NOT_FOUND", "Không tìm thấy hồ sơ học sinh.", frappe.DoesNotExistError, 404)
		try:
			doc = frappe.get_doc("CRM Student", canonical_id)
			activity_id = canonical_id
		except frappe.DoesNotExistError:
			_raise_api_error("STUDENT_NOT_FOUND", "Không tìm thấy hồ sơ học sinh.", frappe.DoesNotExistError, 404)

	if canonical_id and not frappe.has_permission("CRM Student", "read", canonical_id):
		_raise_api_error("STUDENT_NOT_FOUND", "Không tìm thấy hồ sơ học sinh.", frappe.DoesNotExistError, 404)
	if not doc.has_permission("read"):
		_raise_api_error("STUDENT_NOT_FOUND", "Không tìm thấy hồ sơ học sinh.", frappe.DoesNotExistError, 404)

	row = _normalize_student_row(frappe._dict({field: doc.get(field) for field in STUDENT_FIELDS}))
	interactions = _student_interactions(activity_id)
	guardian = _student_guardian(activity_id)
	if not guardian.get("name") and row.get("alt_name"):
		guardian.update({"name": row.get("alt_name"), "preferredChannel": None, "consentStatus": None})

	zalo_messages = _student_zalo_messages(activity_id, interactions, row, guardian)
	calls = _student_call_records(activity_id, interactions, row, guardian)

	return {
		"student_id": requested_id,
		"zalo_messages": zalo_messages,
		"calls": calls,
		"total_interactions": len(interactions),
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_lead_call_logs(lead_id: str) -> dict[str, Any]:
	"""Return permission-scoped call history for one CRM Lead."""
	payload = get_student_interactions(lead_id)
	calls = payload.get("calls") or []
	return {
		"lead_id": payload.get("student_id"),
		"calls": calls,
		"total": len(calls),
	}


CHATWOOT_INTERACTION_FIELDS = [
	"name",
	"student",
	"crm_contact",
	"interaction_type",
	"interaction_datetime",
	"summary",
	"notes",
	"channel",
	"direction",
	"conversation_id",
	"agent_id",
	"outcome",
	"actor",
	"source_namespace",
	"source_record_id",
	"creation",
]


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_student_chatwoot_interactions(
	student_id: str,
	page: str | int = 1,
	page_size: str | int = 50,
) -> dict[str, Any]:
	"""Return permission-aware Chatwoot interactions for one Student."""
	_require_access()
	requested_id, lead_id, canonical_id = _resolve_activity_target(student_id)
	if not requested_id:
		_raise_api_error("INVALID_STUDENT_ID", "studentId không được để trống.", frappe.ValidationError, 400)

	try:
		doc = frappe.get_doc("CRM Lead", lead_id)
	except frappe.DoesNotExistError:
		_raise_api_error("STUDENT_NOT_FOUND", "Không tìm thấy hồ sơ học sinh.", frappe.DoesNotExistError, 404)

	if canonical_id and not frappe.has_permission("CRM Student", "read", canonical_id):
		_raise_api_error("STUDENT_NOT_FOUND", "Không tìm thấy hồ sơ học sinh.", frappe.DoesNotExistError, 404)
	if not doc.has_permission("read"):
		_raise_api_error("STUDENT_NOT_FOUND", "Không tìm thấy hồ sơ học sinh.", frappe.DoesNotExistError, 404)

	page_number = _parse_int(page, "page", 1, minimum=1)
	page_length = _parse_int(page_size, "page_size", 50, minimum=1, maximum=100)
	canonical_id = canonical_id or canonical_student(lead_id) or lead_id
	filters = {
		"student": lead_id,
		"interaction_type": ["in", CHATWOOT_INTERACTION_TYPES],
	}
	rows = frappe.get_list(
		"CRM Interaction",
		filters=filters,
		fields=CHATWOOT_INTERACTION_FIELDS,
		order_by="interaction_datetime desc, creation desc, name desc",
		limit_start=(page_number - 1) * page_length,
		limit_page_length=page_length,
	)
	all_visible_names = frappe.get_list(
		"CRM Interaction",
		filters=filters,
		fields=["name"],
		limit_page_length=0,
		pluck="name",
	)
	guardian = _student_guardian(lead_id)
	student_row = frappe._dict({field: doc.get(field) for field in STUDENT_FIELDS})
	if not guardian.get("name") and student_row.get("alt_name"):
		guardian.update(
			{"name": student_row.get("alt_name"), "preferredChannel": None, "consentStatus": None}
		)

	return {
		"student_id": requested_id,
		"data": rows,
		"zalo_messages": _student_zalo_messages(lead_id, rows, student_row, guardian),
		"meta": {
			"page": page_number,
			"page_size": page_length,
			"total": len(all_visible_names),
			"has_next_page": page_number * page_length < len(all_visible_names),
		},
	}


def _parse_query(
	*,
	admissionYear: str | int | None = None,
	page: str | int = 1,
	pageSize: str | int = 20,
	q: str | None = "",
	stage: str | None = None,
	province: str | None = None,
	ownerId: str | None = None,
	sort: str = "score",
	order: str = "desc",
	assignmentStatus: str | None = None,
	lifecycleStatus: str | None = None,
	provinceId: str | None = None,
	assignment_status: str | None = None,
	lifecycle_status: str | None = None,
	province_id: str | None = None,
) -> dict[str, Any]:
	"""Normalize and validate public query arguments without touching the DB."""
	admission_year = _parse_admission_year(admissionYear)
	page_number = _parse_int(page, "page", 1, minimum=1)
	page_size = _parse_int(pageSize, "pageSize", 20, minimum=1, maximum=100)
	normalized_stage = _normalize_enum(stage, STAGES, "stage") if stage else None
	assignment_value = _first_query_value(assignmentStatus, assignment_status)
	lifecycle_value = _first_query_value(lifecycleStatus, lifecycle_status)
	if lifecycle_value:
		lifecycle_value = next(
			(
				canonical
				for legacy, canonical in LIFECYCLE_STATUS_ALIASES.items()
				if _fold(str(lifecycle_value)) in {_fold(legacy), _fold(canonical)}
			),
			lifecycle_value,
		)
	province_value = _first_query_value(province, provinceId, province_id)
	normalized_assignment_status = _normalize_optional_enum(
		assignment_value, ASSIGNMENT_STATUSES, "assignmentStatus"
	)
	normalized_lifecycle_status = _normalize_optional_enum(
		lifecycle_value, LIFECYCLE_STATUSES, "lifecycleStatus"
	)
	normalized_sort = _normalize_enum(sort, SORT_FIELDS, "sort")
	normalized_order = str(order or "").strip().lower()
	if normalized_order not in {"asc", "desc"}:
		frappe.throw(_("order must be asc or desc."), frappe.ValidationError)
	owner_id = str(ownerId or "").strip() or None
	if owner_id and len(owner_id) > 140:
		frappe.throw(_("ownerId is invalid."), frappe.ValidationError)
	if (
		normalized_stage
		and normalized_lifecycle_status
		and STAGES[normalized_stage]["student_stage"] != normalized_lifecycle_status
	):
		frappe.throw(_("stage and lifecycleStatus must refer to the same lifecycle."), frappe.ValidationError)

	return {
		"admission_year": admission_year,
		"page": page_number,
		"page_size": page_size,
		"query": str(q or "").strip(),
		"stage": normalized_stage,
		"province": str(province_value or "").strip() or None,
		"owner_id": owner_id,
		"assignment_status": normalized_assignment_status,
		"lifecycle_status": normalized_lifecycle_status,
		"sort": normalized_sort,
		"order": normalized_order,
	}


def _first_query_value(*values: str | None) -> str | None:
	for value in values:
		if value is not None and str(value).strip():
			return value
	return None


def _normalize_optional_enum(
	value: str | None, choices: dict[str, Any], field: str
) -> str | None:
	if not value or _fold(value) == "all":
		return None
	return _normalize_enum(value, choices, field)


def _parse_admission_year(value: str | int | None) -> str | None:
	if value is None or str(value).strip() == "":
		return None
	text = str(value).strip()
	if not re.fullmatch(r"\d{4}", text):
		frappe.throw(_("admissionYear must be a four-digit year."), frappe.ValidationError)
	return text


def _parse_int(
	value: str | int, field: str, default: int, *, minimum: int, maximum: int | None = None
) -> int:
	if value is None or str(value).strip() == "":
		return default
	text = str(value).strip()
	if not re.fullmatch(r"[+-]?\d+", text):
		frappe.throw(_(f"{field} must be an integer."), frappe.ValidationError)
	try:
		parsed = int(text)
	except (TypeError, ValueError):
		frappe.throw(_(f"{field} must be an integer."), frappe.ValidationError)
	if parsed < minimum:
		frappe.throw(_(f"{field} must be at least {minimum}."), frappe.ValidationError)
	if maximum is not None and parsed > maximum:
		frappe.throw(_(f"{field} must be at most {maximum}."), frappe.ValidationError)
	return parsed


def _normalize_enum(value: str, choices: dict[str, Any], field: str) -> str:
	normalized = _fold(str(value or "").strip())
	for key, descriptor in choices.items():
		label = descriptor["label"] if isinstance(descriptor, dict) else key
		if normalized in {_fold(key), _fold(label)}:
			return key
	frappe.throw(_(f"Invalid {field}."), frappe.ValidationError)


def _resolve_admission_year(value: str | None) -> str:
	if value:
		if _exists("CRM Admission Year", value) or _exists("CRM Admission Year", {"year_name": value}):
			return value
		_raise_api_error(
			"INVALID_ADMISSION_YEAR",
			"Kỳ tuyển sinh không hợp lệ.",
			frappe.ValidationError,
			422,
		)

	rows = frappe.get_all(
		"CRM Admission Year",
		filters={"is_active": 1},
		fields=["name", "year_name"],
		order_by="year_name desc",
		limit_page_length=2,
	)
	if rows:
		return rows[0].get("name") or rows[0].get("year_name")

	current_year = str(frappe.utils.now_datetime().year)
	if _exists("CRM Admission Year", current_year):
		return current_year
	_raise_api_error(
		"INVALID_ADMISSION_YEAR",
		"Chưa cấu hình kỳ tuyển sinh hiện hành.",
		frappe.ValidationError,
		422,
	)


def _resolve_province(value: str | None) -> str | None:
	if not value:
		return None
	if _exists("CRM Province", value):
		return value
	rows = frappe.get_all(
		"CRM Province",
		fields=["name", "province_name", "province_code"],
		limit_page_length=0,
	)
	needle = _fold(value)
	for row in rows:
		candidates = {row.get("name"), row.get("province_name"), row.get("province_code")}
		if any(needle in {_fold(candidate), _slug(candidate)} for candidate in candidates if candidate):
			return row.get("name")
	return value


def _student_filters(
	query: dict[str, Any], province: str | None
) -> tuple[dict[str, Any], list[list[str]]]:
	filters: dict[str, Any] = _canonical_student_filters(query["admission_year"])
	if query.get("owner_id"):
		filters["owner_staff"] = query["owner_id"]
	if query.get("assignment_status") == "assigned" and not query.get("owner_id"):
		filters["owner_staff"] = ["is", "set"]
	elif query.get("assignment_status") == "unassigned":
		# The Student page is a post-conversion list. Unassigned rows are
		# intentionally excluded even when the legacy filter is requested.
		filters["name"] = "__student_without_owner__"
	if province:
		filters["province"] = province
	if query.get("lifecycle_status"):
		filters["student_stage"] = query["lifecycle_status"]
	if query["stage"]:
		filters["student_stage"] = STAGES[query["stage"]]["student_stage"]
		if query["stage"] == "exploring":
			filters["assessment_status"] = ["!=", "confirmed"]
		elif query["stage"] == "counselling":
			filters["assessment_status"] = "confirmed"

	or_filters: list[list[str]] = []
	if query["query"]:
		pattern = f"%{query['query']}%"
		for field in (
			"name",
			"full_name",
			"lead_code",
			"student_identity",
			"high_school",
			"province",
			"major",
			"owner_staff",
			"source",
		):
			or_filters.append([field, "like", pattern])
		display_code_ids = _display_code_student_ids(query["query"], query["admission_year"])
		if display_code_ids:
			or_filters.append(["name", "in", display_code_ids])
	return filters, or_filters


def _display_code_student_ids(display_code: str, admission_year: str | None) -> list[str]:
	"""Resolve a dashboard display code to canonical CRM Student names.

	``_profile_code`` builds the code from the Student's own technical name, so
	the code can only be matched back against CRM Student rows: a converted
	Student is named ``CRMC-<year>-<sequence>`` while its source Lead keeps its
	own ``ENR-<year>-<sequence>``, and the two sequences never line up. Reading
	the Leads instead made every student detail opened by code a 404.
	"""
	match = _DISPLAY_CODE_RE.fullmatch(str(display_code or "").strip())
	if not match or not admission_year or match.group("year") != str(admission_year):
		return []

	filters: dict[str, Any] = {"admission_year": str(admission_year)}
	sequence = match.group("sequence").lstrip("0")
	if sequence:
		# The code carries the last six digits of the technical name, so the
		# name always ends with the unpadded sequence. An all-zero sequence can
		# only come from a name the code cannot describe, and then falls back to
		# scanning the admission year.
		filters["name"] = ["like", f"%{sequence}"]

	rows = frappe.get_all(
		"CRM Student",
		filters=filters,
		fields=["name", "admission_year"],
		limit_page_length=0,
	)
	normalized_code = display_code.strip().casefold()
	return [row.get("name") for row in rows if _profile_code(row).casefold() == normalized_code]


def _resolve_student_id(student_id: str | None) -> str:
	"""Accept either a canonical CRM Lead name or its dashboard display code."""
	value = str(student_id or "").strip()
	match = _DISPLAY_CODE_RE.fullmatch(value)
	if not match:
		return value

	matches = _display_code_student_ids(value, match.group("year"))
	return matches[0] if len(matches) == 1 else value


def _resolve_activity_target(student_id: str | None) -> tuple[str, str, str | None]:
	"""Resolve a Student Detail ID to the legacy Lead-backed activity target.

	The activity tables still store their legacy ``student``/``reference_docname``
	values as CRM Lead names. Student Detail, however, uses the canonical CRM
	Student ID for its child APIs. Keep that compatibility mapping in one place
	so Zalo, Chatwoot and Call Log queries share the same permission boundary.
	"""
	requested_id = str(student_id or "").strip()
	resolved_id = _resolve_student_id(requested_id)
	canonical_id = canonical_student(resolved_id)
	lead_id = resolved_id if frappe.db.exists("CRM Lead", resolved_id) else None
	if not lead_id and canonical_id:
		lead_id = lead_for_student(canonical_id)
	return requested_id, lead_id or resolved_id, canonical_id


def _canonical_student_filters(admission_year: str | None) -> dict[str, Any]:
	return {
		"admission_year": admission_year,
		"source_lead": ["is", "set"],
		"converted_at": ["is", "set"],
		"owner_staff": ["is", "set"],
		"assigned_to": ["is", "set"],
	}


def _list_scope_student_ids() -> list[str] | None:
	"""Return explicit IDs for the session's Group/Team list-only read scope.

	The normal CRM Student permission hook remains assigned-only for Sale so
	direct CRUD/detail access cannot be widened. This endpoint uses the explicit
	list condition only to expose rows that the session may inspect before
	assigning; all mutation commands perform their own ownership checks. The
	condition targets CRM Lead because Lead is the canonical routing projection.
	"""
	if can_read_full_lead_board():
		return None
	condition = get_student_list_read_condition(doctype="CRM Lead")
	if condition is None:
		return None
	rows = frappe.db.sql(f"select name from `tabCRM Lead` where ({condition})", as_dict=True)
	return [row.get("name") for row in rows if row.get("name")]


def _with_allowed_student_ids(
	filters: dict[str, Any], allowed_student_ids: list[str] | None
) -> dict[str, Any]:
	if allowed_student_ids is None:
		return filters
	return {**filters, "name": ["in", allowed_student_ids]}


def _student_list_reader(allowed_student_ids: list[str] | None):
	"""Use an unrestricted reader for Lead Sale's full Student list."""
	if allowed_student_ids is not None or can_read_full_lead_board():
		return frappe.get_all
	return frappe.get_list


def _count_students(
	filters: dict[str, Any],
	or_filters: list[list[str]] | None = None,
	*,
	allowed_student_ids: list[str] | None = None,
) -> int:
	if allowed_student_ids is not None and not allowed_student_ids:
		return 0
	query_filters = _with_allowed_student_ids(filters, allowed_student_ids)
	get_rows = _student_list_reader(allowed_student_ids)
	rows = get_rows(
		"CRM Student",
		filters=query_filters,
		or_filters=or_filters or [],
		fields=["count(name) as total"],
		limit_page_length=1,
	)
	return int(rows[0].get("total") or 0) if rows else 0


def _fetch_student_rows(
	query: dict[str, Any],
	filters: dict[str, Any],
	or_filters: list[list[str]],
	*,
	allowed_student_ids: list[str] | None = None,
) -> list:
	if query["sort"] != "score":
		return _fetch_computed_sort_rows(
			query,
			filters,
			or_filters,
			allowed_student_ids=allowed_student_ids,
		)

	field = SORT_FIELDS[query["sort"]]
	if allowed_student_ids is not None and not allowed_student_ids:
		return []
	get_rows = _student_list_reader(allowed_student_ids)
	rows = get_rows(
		"CRM Student",
		filters=_with_allowed_student_ids(filters, allowed_student_ids),
		or_filters=or_filters,
		fields=STUDENT_FIELDS,
		order_by=_student_order_by(field, query["order"]),
		limit_start=(query["page"] - 1) * query["page_size"],
		limit_page_length=query["page_size"],
	)
	return _normalize_student_rows(rows)


def _student_order_by(sort_field: str, order: str) -> str:
	"""Keep the list grouped by Student workflow stage before applying the requested sort."""
	return f"{STUDENT_STAGE_ORDER} asc, {sort_field} {order}, name {order}"


def _fetch_computed_sort_rows(
	query: dict[str, Any],
	filters: dict[str, Any],
	or_filters: list[list[str]],
	*,
	allowed_student_ids: list[str] | None = None,
) -> list:
	"""Sort fields that live on related read models, then apply the page window."""
	if allowed_student_ids is not None and not allowed_student_ids:
		return []
	get_rows = _student_list_reader(allowed_student_ids)
	rows = get_rows(
		"CRM Student",
		filters=_with_allowed_student_ids(filters, allowed_student_ids),
		or_filters=or_filters,
		fields=STUDENT_FIELDS,
		order_by="name asc",
		limit_page_length=0,
	)
	rows = _normalize_student_rows(rows)
	student_ids = [row.get("name") for row in rows if row.get("name")]
	related = {}
	if query["sort"] == "priority":
		related = _latest_by_student(
			"CRM Action Item",
			student_ids,
			["student", "priority"],
			"worklist_priority_rank asc, due_at asc, creation asc, name asc",
			filters={"state": ["in", list(ACTIVE_ACTION_STATES)], "current_slot": "CURRENT"},
		)
	elif query["sort"] == "lastActivityAt":
		related = _latest_by_student(
			"CRM Interaction",
			student_ids,
			["student", "interaction_datetime"],
			"interaction_datetime desc, creation desc, name desc",
		)
	elif query["sort"] == "nextActionDueAt":
		related = _latest_by_student(
			"CRM Action Item",
			student_ids,
			["student", "due_at"],
			"due_at asc, worklist_priority_rank asc, creation asc, name asc",
			filters={"state": ["in", list(ACTIVE_ACTION_STATES)], "current_slot": "CURRENT"},
		)

	present, missing = [], []
	for row in rows:
		value = _sort_related_value(query["sort"], related.get(row.get("name")))
		(missing if value is None else present).append((value, row.get("name") or "", row))
	present.sort(key=lambda entry: (entry[0], entry[1]), reverse=query["order"] == "desc")
	missing.sort(key=lambda entry: entry[1])
	sorted_rows = [entry[2] for entry in present + missing]
	sorted_rows.sort(key=_student_stage_rank)
	start = (query["page"] - 1) * query["page_size"]
	return sorted_rows[start : start + query["page_size"]]


def _student_stage_rank(row) -> int:
	return STUDENT_STAGE_RANK.get(str(row.get("student_stage") or "").strip(), 99)


def _sort_related_value(sort_field: str, related) -> int | str | None:
	if not related:
		return None
	if sort_field == "priority":
		rank = PRIORITIES.get(str(related.get("priority") or "").lower(), {"rank": 999})["rank"]
		return 4 - rank if rank != 999 else None
	return _as_iso(related.get("interaction_datetime") or related.get("due_at"))


def _hydrate_rows(rows: list, sort_field: str | None = None) -> list[dict[str, Any]]:
	if not rows:
		return []
	rows = _normalize_student_rows(rows)
	student_ids = [row.get("name") for row in rows if row.get("name")]
	lookups = _load_lookups(rows)
	activities = _latest_by_student(
		"CRM Interaction",
		student_ids,
		[
			"name",
			"student",
			"interaction_datetime",
			"summary",
			"channel",
			"interaction_type",
			"next_follow_up_action",
		],
		"interaction_datetime desc, creation desc, name desc",
	)
	actions = _latest_by_student(
		"CRM Action Item",
		student_ids,
		["name", "student", "action", "objective", "priority", "due_at", "action_owner", "action_type"],
		"due_at asc, worklist_priority_rank asc, creation asc, name asc"
		if sort_field == "nextActionDueAt"
		else "worklist_priority_rank asc, due_at asc, creation asc, name asc",
		filters={"state": ["in", list(ACTIVE_ACTION_STATES)], "current_slot": "CURRENT"},
	)
	score_history = _latest_by_student(
		"CRM Score History",
		student_ids,
		["name", "student", "score_change", "final_score", "scoring_time"],
		"scoring_time desc, creation desc, name desc",
	)
	return [
		_map_student_row(
			row,
			lookups=lookups,
			activity=activities.get(row.get("name")),
			action=actions.get(row.get("name")),
			score_history=score_history.get(row.get("name")),
		)
		for row in rows
	]


def _normalize_student_row(row) -> Any:
	return _normalize_student_rows([row])[0]


def _normalize_student_rows(rows: list) -> list:
	"""Normalize canonical CRM Student fields for the existing dashboard mapper.

	The dashboard projection historically consumed CRM Lead-shaped rows. Keeping
	this small adapter lets the rest of the read model use stable response keys
	while making CRM Student the only source of rows.
	"""
	if not rows:
		return []
	source_leads = {
		row.get("source_lead")
		for row in rows
		if row.get("source_lead")
	}
	lead_statuses = {}
	if source_leads:
		lead_statuses = {
			row.name: row
			for row in frappe.get_all(
				"CRM Lead",
				filters={"name": ["in", list(source_leads)]},
				fields=["name", "processing_status", "resolution", "ownership_revision"],
				limit_page_length=0,
				ignore_permissions=True,
			)
		}
	normalized = []
	for row in rows:
		item = frappe._dict(row)
		item.student_name = item.get("student_name") or item.get("full_name")
		item.case_key = item.get("case_key") or item.get("student_identity")
		item.student = item.get("student") or item.get("name")
		item.processing_status = item.get("processing_status")
		item.resolution = item.get("resolution")
		lead_status = lead_statuses.get(item.get("source_lead"))
		if lead_status:
			item.processing_status = lead_status.get("processing_status")
			item.resolution = lead_status.get("resolution")
			item.ownership_revision = lead_status.get("ownership_revision")
		if item.get("ownership_revision") is None:
			item.ownership_revision = item.get("student_context_revision")
		normalized.append(item)
	return normalized


def _load_lookups(rows: list) -> dict[str, dict[str, str]]:
	return {
		"schools": _lookup_map("CRM High School", {row.get("high_school") for row in rows}, "school_name"),
		"provinces": _lookup_map("CRM Province", {row.get("province") for row in rows}, "province_name"),
		"majors": _lookup_map("CRM Major", {row.get("major") for row in rows}, "major_name"),
		"owners": _lookup_map("CRM Staff", {row.get("owner_staff") for row in rows}, "full_name"),
		"sources": _lookup_map("CRM Lead Source", {row.get("source") for row in rows}, "source_name"),
	}


def _lookup_map(doctype: str, names: set[str | None], label_field: str) -> dict[str, str]:
	keys = [name for name in names if name]
	if not keys or not _table_exists(doctype):
		return {}
	rows = frappe.get_all(
		doctype, filters={"name": ["in", keys]}, fields=["name", label_field], limit_page_length=0
	)
	return {row.get("name"): row.get(label_field) or row.get("name") for row in rows}


def _latest_by_student(
	doctype: str,
	student_ids: list[str],
	fields: list[str],
	order_by: str,
	filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
	if not student_ids or not _table_exists(doctype):
		return {}
	query_ids = _student_query_ids(student_ids)
	query_filters = {"student": ["in", query_ids], **(filters or {})}
	rows = frappe.get_all(
		doctype, filters=query_filters, fields=fields, order_by=order_by, limit_page_length=0
	)
	requested_by_reference = {value: value for value in student_ids}
	for value in student_ids:
		canonical = canonical_student(value)
		if canonical:
			requested_by_reference[canonical] = value
	result = {}
	for row in rows:
		key = requested_by_reference.get(row.get("student"), row.get("student"))
		if key and key not in result:
			result[key] = row
	return result


def _student_query_ids(student_ids: list[str]) -> list[str]:
	"""Include Lead and canonical Student IDs for migrated child doctypes."""
	values: list[str] = []
	seen: set[str] = set()
	for value in student_ids:
		for candidate in (value, canonical_student(value)):
			if candidate and candidate not in seen:
				seen.add(candidate)
				values.append(candidate)
	return values


def _map_student_row(row, *, lookups=None, activity=None, action=None, score_history=None) -> dict[str, Any]:
	lookups = lookups or {}
	stage = _stage_descriptor(row)
	priority = _priority_descriptor(action)
	activity_at = activity.get("interaction_datetime") if activity else None
	next_action = (action.get("objective") if action else None) or (
		activity.get("next_follow_up_action") if activity else None
	)
	owner_key = (action.get("action_owner") if action else None) or row.get("owner_staff")
	owner = lookups.get("owners", {}).get(owner_key) or owner_key
	revision = row.get("ownership_revision")
	if revision is None:
		frappe.throw(
			_("Student {0} is missing ownership revision.").format(row.get("name") or "unknown"),
			frappe.ValidationError,
		)
	try:
		revision = int(revision)
	except (TypeError, ValueError):
		frappe.throw(
			_("Student {0} has an invalid ownership revision.").format(row.get("name") or "unknown"),
			frappe.ValidationError,
		)
	if revision < 0:
		frappe.throw(
			_("Student {0} has an invalid ownership revision.").format(row.get("name") or "unknown"),
			frappe.ValidationError,
		)
	return {
		"id": row.get("name"),
		"studentId": row.get("student"),
		"initials": _initials(row.get("student_name")),
		"name": row.get("student_name") or row.get("name"),
		"code": _profile_code(row),
		"school": lookups.get("schools", {}).get(row.get("high_school")) or row.get("high_school"),
		"province": lookups.get("provinces", {}).get(row.get("province")) or row.get("province"),
		"provinceId": row.get("province"),
		"major": lookups.get("majors", {}).get(row.get("major")) or row.get("major"),
		"stage": stage["label"] if stage else None,
		"studentStage": _student_stage_value(row),
		"processingStatus": row.get("processing_status"),
		"resolution": row.get("resolution"),
		"sourceLead": row.get("source_lead"),
		"campaign": row.get("campaign"),
		"recordType": "student",
		"assignmentStatus": "assigned"
		if row.get("owner_staff") or row.get("assigned_to")
		else "unassigned",
		"score": _number(row.get("latest_score")),
		"scoreDelta": _number(score_history.get("score_change")) if score_history else None,
		"lastActivity": _relative_time(activity_at),
		"lastActivityAt": _as_iso(activity_at) if activity_at else None,
		"nextAction": next_action,
		"nextActionCode": action.get("action") if action else None,
		"nextActionType": action.get("action_type") if action else None,
		"nextActionDueAt": _as_iso(action.get("due_at")) if action and action.get("due_at") else None,
		"owner": owner,
		"revision": revision,
		"source": lookups.get("sources", {}).get(row.get("source")) or row.get("source"),
		"priority": priority["label"] if priority else None,
		"priorityCode": action.get("priority") if action else None,
		"stageCode": stage["code"] if stage else None,
	}


def _profile_code(row) -> str:
	"""Return the human-readable code shown in the dashboard.

	The canonical case key remains an internal Frappe identity for crm-agents.
	This display code is stable, non-sensitive, and derived from the technical
	Student name plus the admission cycle and the current HCM admissions branch.
	"""
	student_id = str(row.get("name") or "")
	code = hs_code_for_reference(student_id, row.get("admission_year"))
	if not code:
		code = hs_code_for_reference(row.get("lead_code"), row.get("admission_year"))
	if code:
		return code
	match = re.search(r"(?:ENR|CRMC)-(\d{4})-(\d+)$", student_id)
	year = str(row.get("admission_year") or (match.group(1) if match else "2026"))
	sequence = match.group(2)[-6:].zfill(6) if match else "000000"
	region = "HCM"
	return f"HS-{year}-{region}-{sequence}"


def _student_stage_value(row) -> str | None:
	"""Read the canonical Student stage without fabricating a default."""
	student = canonical_student(row.get("student") or row.get("name"))
	if student:
		stage = frappe.db.get_value("CRM Student", student, "student_stage")
		if stage:
			return stage
	return row.get("student_stage") or None


def _stage_descriptor(row) -> dict[str, str] | None:
	student_stage = str(_student_stage_value(row) or "").strip()
	if student_stage == "Attempting":
		stage_code = "counselling" if row.get("assessment_status") == "confirmed" else "exploring"
		return {"code": stage_code, "label": STAGES[stage_code]["label"]}
	return STAGE_BY_STUDENT_STAGE.get(student_stage)


def _priority_descriptor(action) -> dict[str, Any] | None:
	if not action:
		return None
	return PRIORITIES.get(str(action.get("priority") or "").strip().lower())


def _build_summary(
	admission_year: str, *, allowed_student_ids: list[str] | None = None
) -> dict[str, Any]:
	if allowed_student_ids is not None and not allowed_student_ids:
		rows = []
	else:
		get_rows = _student_list_reader(allowed_student_ids)
		rows = get_rows(
			"CRM Student",
			filters=_with_allowed_student_ids(
				_canonical_student_filters(admission_year), allowed_student_ids
			),
			fields=["name", "latest_score", "interest_level", "assessment_status"],
			limit_page_length=0,
		)
	student_ids = [row.get("name") for row in rows if row.get("name")]
	high_intent = [row for row in rows if _is_confirmed_high_intent(row)]
	probabilities = _confirmed_probabilities(student_ids)
	if allowed_student_ids is not None and not allowed_student_ids:
		previous_rows = []
	else:
		previous_rows = get_rows(
			"CRM Student",
			filters=_with_allowed_student_ids(
				_canonical_student_filters(str(int(admission_year) - 1)), allowed_student_ids
			),
			fields=["name"],
			limit_page_length=0,
		)
	return {
		"trackedStudents": len(rows),
		"trackedStudentsDeltaPercent": _percent_delta(len(rows), len(previous_rows)),
		"highIntentStudents": len(high_intent),
		"highIntentRate": _rate(len(high_intent), len(rows)),
		"actionsDueToday": _count_due_actions(student_ids),
		"averageEnrollmentProbability": round(mean(probabilities), 1) if probabilities else None,
		"averageEnrollmentProbabilityDelta": None,
	}


def _build_action_summary(
	admission_year: str, *, allowed_student_ids: list[str] | None = None
) -> dict[str, Any]:
	if allowed_student_ids is not None and not allowed_student_ids:
		student_ids = []
	else:
		get_rows = _student_list_reader(allowed_student_ids)
		student_ids = [
			row.get("name")
			for row in get_rows(
				"CRM Student",
				filters=_with_allowed_student_ids(
					_canonical_student_filters(admission_year), allowed_student_ids
				),
				fields=["name"],
				limit_page_length=0,
			)
			if row.get("name")
		]
	return {
		"actionsDueToday": _count_due_actions(student_ids),
		# No canonical declining-interaction rule has been released yet.
		"decliningInteractionStudents": None,
		# Do not infer family readiness from a missing guardian/consent record.
		"familyReadyStudents": None,
	}


def _confirmed_probabilities(student_ids: list[str]) -> list[float]:
	if not student_ids or not _table_exists("CRM Student Assessment"):
		return []
	rows = frappe.get_all(
		"CRM Student Assessment",
		filters={"status": "confirmed"},
		or_filters=[
			["crm_student", "in", _student_query_ids(student_ids)],
			["student", "in", _student_query_ids(student_ids)],
		],
		fields=["student", "crm_student", "enrollment_probability"],
		order_by="assessed_at desc, creation desc, name desc",
		limit_page_length=0,
	)
	latest = {}
	for row in rows:
		student = row.get("crm_student") or row.get("student")
		if student not in latest and row.get("enrollment_probability") is not None:
			latest[student] = float(row.get("enrollment_probability"))
	return list(latest.values())


def _count_due_actions(student_ids: list[str]) -> int:
	if not student_ids or not _table_exists("CRM Action Item"):
		return 0
	now = frappe.utils.now_datetime()
	start = now.replace(hour=0, minute=0, second=0, microsecond=0)
	end = start + timedelta(days=1)
	rows = frappe.get_all(
		"CRM Action Item",
		filters={
			"student": ["in", _student_query_ids(student_ids)],
			"state": ["in", list(ACTIVE_ACTION_STATES)],
			"current_slot": "CURRENT",
			"due_at": ["between", [start, end]],
		},
		fields=["student"],
		limit_page_length=0,
	)
	return len({row.get("student") for row in rows if row.get("student")})


def _build_student_360(row, item) -> dict[str, Any]:
	student_id = row.get("name")
	assessment = _latest_assessment(student_id)
	interactions = _student_interactions(student_id)
	probability_trend = _student_probability_trend(student_id, interactions)
	channel_performance = _channel_performance(interactions)
	guardian = _student_guardian(student_id)
	if not guardian.get("name") and row.get("alt_name"):
		guardian.update({"name": row.get("alt_name"), "preferredChannel": None, "consentStatus": None})
	if interactions:
		guardian["lastInteraction"] = _relative_time(interactions[0].get("interaction_datetime"))
	applications = _student_applications(student_id, row.get("admission_year"))
	stage = _stage_descriptor(row) or {"code": "", "label": ""}
	score = item.get("score")
	probability = _number(assessment.get("enrollment_probability")) if assessment else None
	baseline = probability_trend[0]["score"] if probability_trend else None

	return {
		"student": {
			"id": row.get("name"),
			"studentId": row.get("student"),
			"initials": item.get("initials"),
			"name": item.get("name"),
			"code": item.get("code"),
			"school": item.get("school"),
			"grade": _grade_label(row),
			"major": item.get("major"),
			"phone": row.get("phone"),
			"email": row.get("email"),
			"province": item.get("province"),
			"counselor": item.get("owner"),
			"revision": item.get("revision"),
			"studentStage": item.get("studentStage") or _student_stage_value(row),
			"priority": item.get("priority"),
			"verificationStatus": _verification_status(row, assessment),
			"contactConsent": _contact_consent(student_id, row.get("privacy_status")),
			"lastUpdatedAt": _as_iso(row.get("modified")),
		},
		"readiness": _readiness(row, item, guardian, applications, interactions),
		"profile": _key_values(
			[
				("Ngày sinh", _display_date(row.get("date_of_birth"))),
				("Giới tính", row.get("gender")),
				("Khu vực", item.get("province")),
				("Nguồn", item.get("source")),
				("Phụ trách", item.get("owner")),
			]
		),
		"academics": _key_values(
			[
				("Lớp", _grade_label(row)),
				("Trường", item.get("school")),
				("Điểm tốt nghiệp", row.get("graduation_score")),
				("Điểm học bạ", row.get("transcript_score")),
				("Tiếng Anh", row.get("english_converted_score")),
				("Phương thức xét tuyển", row.get("admission_method")),
			]
		),
		"family": _key_values(
			[
				("Người liên hệ", guardian.get("name")),
				("Quan hệ", guardian.get("relation")),
				("Kênh ưu tiên", guardian.get("preferredChannel")),
			]
		),
		"classification": _classification(row, item, assessment, stage),
		"acquisition": _acquisition(row, item),
		"segmentation": _segmentation(row, item),
		"parentProfile": guardian,
		"insight": {
			"summary": _insight_summary(stage["label"], score),
			"signalScore": score,
			"probability": probability,
			"potentialLabel": _potential_label(probability),
			"priorityThreshold": PRIORITY_THRESHOLD,
			"scoreDelta": item.get("scoreDelta"),
			"baseline": baseline,
			"confidence": _assessment_confidence(assessment),
			"concern": row.get("primary_barrier"),
			"decisionMaker": guardian.get("name"),
			"evidence": [text for text in (assessment.get("reason"), row.get("primary_barrier")) if text],
			"recommendation": assessment.get("recommendation") if assessment else item.get("nextAction"),
		},
		"journey": _journey(interactions, item),
		"engagement": _engagement(interactions),
		"application": _application_items(applications),
		"probabilityTrend": probability_trend,
		"channelPerformance": channel_performance,
		"zaloMessages": _student_zalo_messages(student_id, interactions, row, guardian),
		"calls": _student_call_records(student_id, interactions, row, guardian),
	}


def _latest_assessment(student_id: str | None):
	rows = _assessment_history(
		student_id,
		order_by="assessed_at desc, creation desc",
		exclude_rejected=True,
		limit_page_length=1,
	)
	return rows[0] if rows else frappe._dict()


def _assessment_history(
	student_id: str | None,
	*,
	order_by: str,
	exclude_rejected: bool = False,
	limit_page_length: int = 0,
) -> list:
	if not student_id or not _table_exists("CRM Student Assessment"):
		return []
	student_ids = _student_query_ids([student_id])
	filters: dict[str, Any] = {}
	if exclude_rejected:
		filters["status"] = ["!=", "rejected"]
	return frappe.get_all(
		"CRM Student Assessment",
		filters=filters,
		or_filters=[
			["crm_student", "in", student_ids],
			["student", "in", student_ids],
		],
		fields=ASSESSMENT_FIELDS,
		order_by=order_by,
		limit_page_length=limit_page_length,
	)


def _student_probability_trend(student_id: str | None, interactions: list) -> list[dict[str, Any]]:
	return _build_probability_trend(
		_assessment_history(student_id, order_by="assessed_at asc, creation asc, name asc"), interactions
	)


def _build_probability_trend(assessments: list, interactions: list) -> list[dict[str, Any]]:
	chart_interactions = _prepared_chart_interactions(interactions)
	trend = []
	for assessment in assessments:
		if assessment.get("status") == "rejected":
			continue
		score = _number(assessment.get("enrollment_probability"))
		assessed_at = _local_datetime(assessment.get("assessed_at"))
		if score is None or assessed_at is None:
			continue

		point = {
			"date": assessed_at.isoformat(timespec="seconds"),
			"score": max(0, min(100, score)),
			"touches": sum(when <= assessed_at for when, _, _ in chart_interactions),
		}
		related = next(
			(
				(interaction, channel)
				for when, interaction, channel in reversed(chart_interactions)
				if when <= assessed_at
			),
			None,
		)
		if related:
			interaction, channel = related
			point.update(
				{
					"eventTitle": interaction.get("summary") or interaction.get("interaction_type"),
					"eventDetail": interaction.get("notes") or interaction.get("next_follow_up_action"),
					"channel": channel,
				}
			)
		trend.append(point)
	return trend


def _student_interactions(student_id: str | None) -> list:
	if not student_id or not _table_exists("CRM Interaction"):
		return []
	student_ids = _student_query_ids([student_id])
	return frappe.get_all(
		"CRM Interaction",
		filters={"student": ["in", student_ids]},
		fields=[
			"name",
			"interaction_datetime",
			"interaction_type",
			"summary",
			"notes",
			"channel",
			"direction",
			"outcome",
			"next_follow_up_action",
			"actor",
			"crm_contact",
			"conversation_id",
			"source_record_id",
			"evidence",
			"reference_doctype",
			"reference_docname",
		],
		order_by="interaction_datetime desc, creation desc",
		limit_page_length=50,
	)


def _user_name(user_id: str | None, fallback: str = "Tư vấn viên") -> str:
	if not user_id:
		return fallback
	try:
		return frappe.get_cached_value("User", user_id, "full_name") or user_id
	except Exception:
		return user_id


def _format_activity_time(value) -> str:
	if not value:
		return ""
	local_dt = _local_datetime(value)
	if local_dt:
		return local_dt.strftime("%d/%m/%Y · %H:%M")
	return str(value)


def _plain_note_text(value: Any) -> str:
	text = str(value or "")
	text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
	text = re.sub(r"</(?:p|div|li)>\s*", "\n", text, flags=re.IGNORECASE)
	text = re.sub(r"<[^>]+>", "", text)
	text = html.unescape(text)
	return re.sub(r"\n{3,}", "\n\n", text).strip()


def _call_note_projection(content: Any) -> dict[str, str | None]:
	"""Extract safe plain-text transcript and summary blocks from an STT note."""
	plain_content = _plain_note_text(content)
	transcript_match = _TRANSCRIPT_BLOCK_RE.search(plain_content)
	summary_match = _SUMMARY_BLOCK_RE.search(plain_content)
	transcript = _plain_note_text(transcript_match.group(1)) if transcript_match else None
	summary = None
	if summary_match:
		summary_body = _plain_note_text(summary_match.group(1))
		try:
			payload = json.loads(summary_body)
			if isinstance(payload, dict) and payload.get("summary"):
				summary = str(payload["summary"]).strip()
		except (TypeError, json.JSONDecodeError):
			# Keep compatibility with notes created before the JSON summary contract.
			for line in summary_body.splitlines():
				if re.match(r"^\s*summary\s*:", line, flags=re.IGNORECASE):
					summary = re.sub(r"^\s*summary\s*:\s*", "", line, flags=re.IGNORECASE).strip()
					break
	return {"transcript": transcript or None, "summary": summary or None}


def _call_note_projections(call_logs: list) -> dict[str, dict[str, str | None]]:
	"""Load Call Log notes in one permission-aware query."""
	note_names = sorted({str(row.get("note") or "").strip() for row in call_logs if row.get("note")})
	if not note_names or not _table_exists("FCRM Note"):
		return {}
	try:
		notes = frappe.get_list(
			"FCRM Note",
			filters={"name": ["in", note_names]},
			fields=["name", "content"],
			limit_page_length=0,
		)
	except frappe.PermissionError:
		return {}
	return {str(note.get("name")): _call_note_projection(note.get("content")) for note in notes}


def _student_zalo_messages(
	student_id: str | None,
	interactions: list,
	student_row=None,
	guardian=None,
) -> list[dict[str, Any]]:
	if not student_id:
		return []

	student_name = (student_row.get("student_name") if student_row else None) or "Học sinh"
	parent_name = guardian.get("name") if guardian else None
	parent_role = (guardian.get("relation") if guardian else None) or "Phụ huynh"
	staff_name = _user_name(
		student_row.get("assigned_to")
		if student_row
		else None or student_row.get("owner_staff")
		if student_row
		else None,
		fallback="Tư vấn viên",
	)

	messages: list[dict[str, Any]] = []
	for ix in interactions:
		channel = _fold(ix.get("channel") or "")
		interaction_type = _fold(ix.get("interaction_type") or "")
		is_chatwoot_message = interaction_type in {_fold(value) for value in CHATWOOT_INTERACTION_TYPES}
		if "zalo" not in channel and "zalo" not in interaction_type and not is_chatwoot_message:
			continue

		direction = "inbound" if _fold(ix.get("direction") or "") in {"inbound", "incoming"} else "outbound"
		actor_name = _user_name(ix.get("actor"), fallback=staff_name)

		contact_name = parent_name if parent_name else student_name
		contact_role = parent_role if parent_name else "Học sinh"

		if direction == "inbound":
			sender_name = contact_name
			sender_role = contact_role
			recipient_name = actor_name
			recipient_role = "Tư vấn viên"
		else:
			sender_name = actor_name
			sender_role = "Tư vấn viên"
			recipient_name = contact_name
			recipient_role = contact_role

		raw_outcome = ix.get("outcome") or ""
		outcome_fold = _fold(raw_outcome)
		if outcome_fold in {"resolved", "captured", "converted"}:
			status = "read"
		elif outcome_fold in {"follow up needed", "connected"}:
			status = "delivered"
		elif outcome_fold in {"data error", "uncontactable", "no response"}:
			status = "failed"
		else:
			status = "delivered" if direction == "outbound" else "read"

		content = ix.get("notes") or ix.get("summary") or "Tin nhắn Zalo"
		summary = ix.get("summary") or "Trao đổi qua Zalo"

		attachment_name = None
		notes_text = str(ix.get("notes") or "")
		if any(ext in notes_text.lower() for ext in (".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg")):
			match = re.search(r"([\w\d_.-]+\.(?:pdf|docx|xlsx|png|jpg|jpeg))", notes_text, re.IGNORECASE)
			if match:
				attachment_name = match.group(1)

		messages.append(
			{
				"id": str(ix.get("name")),
				"time": _format_activity_time(ix.get("interaction_datetime")),
				"senderName": sender_name,
				"senderRole": sender_role,
				"recipientName": recipient_name,
				"recipientRole": recipient_role,
				"content": content,
				"direction": direction,
				"status": status,
				"conversationTitle": summary,
				"attachmentName": attachment_name,
			}
		)

	return messages


def _student_call_records(
	student_id: str | None,
	interactions: list,
	student_row=None,
	guardian=None,
) -> list[dict[str, Any]]:
	if not student_id:
		return []

	student_name = (student_row.get("student_name") if student_row else None) or "Học sinh"
	parent_name = guardian.get("name") if guardian else None
	parent_role = (guardian.get("relation") if guardian else None) or "Phụ huynh"
	student_phone = (student_row.get("phone") if student_row else None) or ""
	staff_name = _user_name(
		student_row.get("assigned_to")
		if student_row
		else None or student_row.get("owner_staff")
		if student_row
		else None,
		fallback="Tư vấn viên",
	)

	contact_name = parent_name if parent_name else student_name
	contact_role = parent_role if parent_name else "Học sinh"

	calls: list[dict[str, Any]] = []
	seen_call_ids: set[str] = set()
	canonical_calls_by_source_id: dict[str, Any] = {}
	for ix in interactions:
		source_record_id = str(ix.get("source_record_id") or "").strip()
		channel = _fold(ix.get("channel") or "")
		interaction_type = _fold(ix.get("interaction_type") or "")
		if source_record_id and (
			"call" in channel
			or "phone" in channel
			or "call" in interaction_type
			or "phone" in interaction_type
		):
			canonical_calls_by_source_id[source_record_id] = ix

	if _table_exists("Call Log"):
		try:
			activity_ids = _student_query_ids([student_id])
			call_logs = frappe.get_list(
				"Call Log",
				filters={"reference_docname": ["in", activity_ids]},
				or_filters=[
					{"reference_doctype": "CRM Student"},
					{"reference_doctype": "CRM Lead"},
				],
				fields=[
					"name",
					"caller",
					"receiver",
					"from",
					"to",
					"duration",
					"start_time",
					"status",
					"type",
					"recording_url",
					"telephony_medium",
					"medium",
					"creation",
					"note",
				],
				order_by="start_time desc, creation desc",
				limit_page_length=50,
			)
		except frappe.PermissionError:
			# Sale and CTV Sale hold no Call Log read grant, so a telephony
			# permission gap must degrade to an empty call history the way the
			# Lead projection already does -- never break the whole 360 detail.
			call_logs = []
		note_projections = _call_note_projections(call_logs)
		for cl in call_logs:
			call_log_id = str(cl.get("name") or "").strip()
			seen_call_ids.add(call_log_id)
			canonical = canonical_calls_by_source_id.get(call_log_id)
			is_inbound = _fold(cl.get("type") or "") in {"incoming", "inbound"}
			duration_secs = int(cl.get("duration") or 0)
			status_fold = _fold(cl.get("status") or "")
			if status_fold in {"completed", "connected"}:
				outcome = "connected"
			elif status_fold in {"no answer", "busy", "canceled"}:
				outcome = "no-answer"
			elif status_fold in {"missed", "failed"}:
				outcome = "missed"
			else:
				outcome = "connected" if duration_secs > 0 else "no-answer"

			if is_inbound:
				direction = "inbound"
				caller_name = _user_name(cl.get("caller"), fallback=contact_name)
				caller_role = contact_role
				receiver_name = _user_name(cl.get("receiver"), fallback=staff_name)
				receiver_role = "Tư vấn viên"
				phone_number = cl.get("from") or student_phone
			else:
				direction = "outbound"
				caller_name = _user_name(cl.get("caller"), fallback=staff_name)
				caller_role = "Tư vấn viên"
				receiver_name = _user_name(cl.get("receiver"), fallback=contact_name)
				receiver_role = contact_role
				phone_number = cl.get("to") or student_phone

			note_projection = note_projections.get(str(cl.get("note") or ""), {})
			topic = note_projection.get("summary") or "Cuộc gọi tư vấn"
			summary = note_projection.get("summary") or f"Cuộc gọi {cl.get('status') or ''}"
			summary_available = bool(note_projection.get("summary"))

			calls.append(
				{
					"id": str(cl.get("name")),
					"interactionId": str(canonical.get("name")) if canonical else None,
					"evidenceId": (
						str(canonical.get("evidence"))
						if canonical and canonical.get("evidence")
						else None
					),
					"time": _format_activity_time(cl.get("start_time") or cl.get("creation")),
					"direction": direction,
					"outcome": outcome,
					"callerName": caller_name,
					"receiverName": receiver_name,
					"callerRole": caller_role,
					"receiverRole": receiver_role,
					"phoneNumber": phone_number,
					"durationSeconds": duration_secs,
					"topic": topic,
					"summary": summary,
					"summaryAvailable": summary_available,
					"transcript": note_projection.get("transcript"),
					"recordingUrl": get_recording_url_path(
						cl.get("name"),
						cl.get("recording_url"),
						cl.get("telephony_medium"),
						cl.get("medium"),
					),
				}
			)

	for ix in interactions:
		channel = _fold(ix.get("channel") or "")
		ix_type = _fold(ix.get("interaction_type") or "")
		is_call = (
			"call" in channel
			or "phone" in channel
			or "goi" in channel
			or ix_type in {"connected", "outreach"}
		)
		if not is_call:
			continue

		ref_doc = ix.get("reference_docname")
		if ix.get("reference_doctype") == "Call Log" and ref_doc in seen_call_ids:
			continue
		source_record_id = str(ix.get("source_record_id") or "").strip()
		if source_record_id and source_record_id in seen_call_ids:
			continue
		interaction_id = str(ix.get("name") or "").strip()
		if interaction_id in seen_call_ids:
			continue

		seen_call_ids.add(interaction_id)
		direction = "inbound" if _fold(ix.get("direction") or "") in {"inbound", "incoming"} else "outbound"
		actor_name = _user_name(ix.get("actor"), fallback=staff_name)

		if direction == "inbound":
			caller_name = contact_name
			caller_role = contact_role
			receiver_name = actor_name
			receiver_role = "Tư vấn viên"
		else:
			caller_name = actor_name
			caller_role = "Tư vấn viên"
			receiver_name = contact_name
			receiver_role = contact_role

		raw_outcome = ix.get("outcome") or ""
		outcome_fold = _fold(raw_outcome)
		if outcome_fold in {"resolved", "captured", "converted", "connected"}:
			outcome = "connected"
		elif outcome_fold in {"no response", "uncontactable", "no answer"}:
			outcome = "no-answer"
		elif outcome_fold == "follow up needed":
			outcome = "callback"
		else:
			outcome = "connected"

		topic = ix.get("summary") or "Cuộc gọi tư vấn"
		summary = ix.get("notes") or ix.get("summary") or "Trao đổi qua cuộc gọi."

		calls.append(
			{
				"id": interaction_id,
				"interactionId": interaction_id,
				"evidenceId": str(ix.get("evidence")) if ix.get("evidence") else None,
				"time": _format_activity_time(ix.get("interaction_datetime")),
				"direction": direction,
				"outcome": outcome,
				"callerName": caller_name,
				"receiverName": receiver_name,
				"callerRole": caller_role,
				"receiverRole": receiver_role,
				"phoneNumber": student_phone,
				"durationSeconds": 0,
				"topic": topic,
				"summary": summary,
				"recordingUrl": None,
			}
		)

	return calls


def _channel_performance(interactions: list) -> list[dict[str, Any]]:
	channels: dict[str, dict[str, Any]] = {}
	for prepared in _prepared_chart_interactions(interactions):
		interaction, channel = prepared[1], prepared[2]
		item = channels.setdefault(
			channel, {"channel": channel, "touches": 0, "responsive": 0, "activities": []}
		)
		item["touches"] += 1
		if interaction.get("outcome") in {"Captured", "Follow Up Needed", "Resolved", "Converted"}:
			item["responsive"] += 1
		if len(item["activities"]) < 20:
			item["activities"].append(
				{
					"title": interaction.get("summary") or interaction.get("interaction_type") or "Hoạt động",
					"time": _as_iso(interaction.get("interaction_datetime")),
					"description": interaction.get("notes")
					or interaction.get("next_follow_up_action")
					or interaction.get("outcome"),
				}
			)

	return [
		{
			"channel": item["channel"],
			"touches": item["touches"],
			"response": _rate(item["responsive"], item["touches"]),
			"activities": item["activities"],
		}
		for item in channels.values()
	]


def _prepared_chart_interactions(interactions: list) -> list[tuple[Any, Any, str]]:
	prepared = []
	for interaction in interactions:
		when = _local_datetime(interaction.get("interaction_datetime"))
		channel = _chart_channel(interaction)
		if when is not None and channel:
			prepared.append((when, interaction, channel))
	return sorted(prepared, key=lambda item: item[0])


def _chart_channel(interaction) -> str | None:
	value = _fold(interaction.get("channel") or interaction.get("interaction_type"))
	if not value or any(token in value for token in ("zalo", "phone", "call", "goi")):
		return None
	if any(token in value for token in ("event", "su kien")):
		return "Sự kiện"
	if any(token in value for token in ("application", "ho so", "form")):
		return "Hồ sơ"
	if any(token in value for token in ("web", "website", "landing")):
		return "Website"
	return None


def _verification_status(row, assessment) -> str:
	status = str(assessment.get("status") or row.get("assessment_status") or "").strip().lower()
	return {
		"confirmed": "Đã xác thực",
		"proposed": "Cần xác minh",
		"superseded": "Cần xác minh",
		"rejected": "Chưa xác thực",
	}.get(status, "Chưa xác thực")


def _contact_consent(student_id: str | None, privacy_status: str | None) -> dict[str, Any]:
	result = {"status": _privacy_status_label(privacy_status), "channels": [], "updatedAt": None}
	if not student_id or not _table_exists("CRM Contact Consent Event"):
		return result
	student_ids = _student_query_ids([student_id])
	rows = frappe.get_all(
		"CRM Contact Consent Event",
		filters={"student": ["in", student_ids]},
		fields=["event_type", "occurred_at", "scope"],
		order_by="occurred_at desc, creation desc",
		limit_page_length=1,
	)
	if not rows:
		return result
	event = rows[0]
	result.update(
		{
			"status": {
				"Granted": "Đã đồng ý",
				"Re-subscribed": "Đã đồng ý",
				"Opted Out": "Đã rút lại",
				"Bounced": "Đã rút lại",
				"Suppressed": "Đã rút lại",
			}.get(event.get("event_type"), "Chưa xác định"),
			"channels": _consent_channels(event.get("scope")),
			"updatedAt": _as_iso(event.get("occurred_at")),
		}
	)
	return result


def _privacy_status_label(value: str | None) -> str:
	return {
		"granted": "Đã đồng ý",
		"opted_out": "Đã rút lại",
		"withdrawn": "Đã rút lại",
		"expired": "Đã rút lại",
	}.get(str(value or "").strip().lower(), "Chưa xác định")


def _consent_channels(scope: str | None) -> list[str]:
	value = _fold(scope)
	channels = []
	if "email" in value:
		channels.append("Email")
	if any(token in value for token in ("phone", "telephone", "dien thoai")):
		channels.append("Điện thoại")
	return channels


def _potential_label(probability: float | int | None) -> str | None:
	if probability is None:
		return None
	if probability >= PRIORITY_THRESHOLD:
		return "Tiềm năng cao"
	if probability >= 40:
		return "Tiềm năng vừa"
	return "Cần chú ý"


def _student_guardian(student_id: str | None) -> dict[str, Any]:
	result = {
		"name": None,
		"relation": None,
		"involvement": "Chưa xác định",
		"role": None,
		"concerns": [],
		"preferredChannel": None,
		"bestContactTime": None,
		"consentStatus": None,
		"lastInteraction": None,
	}
	if not student_id or not _table_exists("CRM Student Guardian"):
		return result
	student_ids = _student_query_ids([student_id])
	rows = frappe.get_all(
		"CRM Student Guardian",
		filters={"student": ["in", student_ids], "is_active": 1},
		fields=[
			"contact",
			"relationship",
			"decision_role",
			"involvement",
			"preferred_channel",
			"best_contact_time",
			"consent_summary",
		],
		order_by="modified desc",
		limit_page_length=1,
	)
	if not rows:
		return result
	guardian = rows[0]
	contact_name = guardian.get("contact")
	contact_rows = (
		frappe.get_all(
			"CRM Student",
			filters={"name": contact_name},
			fields=["name", "full_name", "phone", "email"],
			limit_page_length=1,
		)
		if contact_name
		else []
	)
	contact = contact_rows[0] if contact_rows else frappe._dict()
	involvement = {"Primary": "Cao", "Shared": "Trung bình", "Low": "Thấp"}.get(
		guardian.get("involvement"), "Chưa xác định"
	)
	result.update(
		{
			"name": contact.get("full_name") or contact_name,
			"relation": guardian.get("relationship"),
			"involvement": involvement,
			"role": guardian.get("decision_role"),
			"preferredChannel": guardian.get("preferred_channel"),
			"bestContactTime": guardian.get("best_contact_time"),
			"consentStatus": guardian.get("consent_summary"),
		}
	)
	return result


def _student_applications(student_id: str | None, admission_year: str | None) -> list:
	if not student_id or not _table_exists("CRM Admission Application"):
		return []
	student_ids = _student_query_ids([student_id])
	filters: dict[str, Any] = {"student": ["in", student_ids]}
	if admission_year:
		filters["admission_year"] = admission_year
	return frappe.get_all(
		"CRM Admission Application",
		filters=filters,
		fields=[
			"name",
			"major",
			"campus",
			"admission_method",
			"status",
			"document_total",
			"document_completed",
			"deadline",
			"submitted_at",
		],
		order_by="preference_order asc, creation desc",
		limit_page_length=20,
	)


def _readiness(row, item, guardian, applications, interactions) -> list[dict[str, Any]]:
	doc_total = sum(int(application.get("document_total") or 0) for application in applications)
	doc_completed = sum(int(application.get("document_completed") or 0) for application in applications)
	if not doc_total and any(
		application.get("status") in {"Submitted", "Under Review", "Accepted", "Enrolled"}
		for application in applications
	):
		doc_completed = doc_total = 1
	return [
		{
			"label": "Hồ sơ",
			"value": round(100 * doc_completed / doc_total) if doc_total else 0,
			"tone": "success" if doc_total and doc_completed >= doc_total else "warning",
			"detail": f"{doc_completed}/{doc_total} tài liệu" if doc_total else "Chưa có hồ sơ",
		},
		{
			"label": "Gia đình",
			"value": 100 if guardian.get("name") else 0,
			"tone": "success" if guardian.get("name") else "warning",
			"detail": "Đã có người liên hệ" if guardian.get("name") else "Chưa xác định người liên hệ",
		},
		{
			"label": "Tương tác",
			"value": min(100, len(interactions) * 20),
			"tone": "success" if item.get("lastActivityAt") else "error",
			"detail": "Có hoạt động gần đây" if item.get("lastActivityAt") else "Chưa có hoạt động",
		},
	]


def _classification(row, item, assessment, stage):
	interest = assessment.get("interest") or row.get("interest_level")
	fit = assessment.get("fit") or row.get("fit_level")
	barrier = assessment.get("primary_barrier") or row.get("primary_barrier")
	return {
		"dimensions": [
			{
				"id": "journey",
				"label": "Hành trình",
				"value": stage["label"],
				"description": "Giai đoạn hiện tại",
				"evidence": [],
				"tone": "primary",
			},
			{
				"id": "interest",
				"label": "Mức độ quan tâm",
				"value": interest,
				"description": "Theo assessment gần nhất",
				"evidence": [],
				"tone": "success",
			},
			{
				"id": "fit",
				"label": "Độ phù hợp",
				"value": fit,
				"description": "Theo assessment gần nhất",
				"evidence": [],
				"tone": "sky",
			},
			{
				"id": "barrier",
				"label": "Rào cản",
				"value": barrier,
				"description": "Rào cản cần xử lý",
				"evidence": [],
				"tone": "warning",
			},
		],
		"combination": " / ".join(value for value in (interest, fit, barrier) if value),
		"interpretation": _insight_summary(stage["label"], item.get("score")),
		"action": item.get("nextAction"),
		"updatedAt": _as_iso(assessment.get("assessed_at")) if assessment.get("assessed_at") else None,
		"updateTrigger": assessment.get("assessment_source"),
		"reviewStatus": "Đã xác nhận" if assessment.get("status") == "confirmed" else "Chờ xác nhận",
		"reviewedBy": None,
	}


def _assessment_confidence(assessment) -> float | int | None:
	values = [
		_number(assessment.get(field))
		for field in ("interest_confidence", "fit_confidence", "barrier_confidence")
		if assessment.get(field) is not None
	]
	return round(mean(values), 1) if values else None


def _acquisition(row, item):
	source = str(item.get("source") or "")
	return {
		"firstTouch": source,
		"sourceGroup": _source_group(source),
		"campaign": row.get("campaign") or "",
		"capturedAt": None,
		"attributionModel": "CRM Student source",
		"consent": "",
	}


def _segmentation(row, item):
	return {
		"learningStage": _grade_label(row),
		"approachGoal": row.get("interest_level"),
		"geographyTier": item.get("province"),
		"geographyImplication": "",
		"schoolTier": item.get("school"),
		"economicContext": "",
		"economicUsage": "",
	}


def _journey(interactions, item):
	milestones = [interaction for interaction in interactions if _is_journey_milestone(interaction)]
	journey = []
	for index, interaction in enumerate(reversed(milestones)):
		journey.append(
			{
				"id": interaction.get("name"),
				"date": _as_iso(interaction.get("interaction_datetime")),
				"title": interaction.get("summary") or interaction.get("channel") or "Hoạt động",
				"description": interaction.get("next_follow_up_action") or "",
				"channel": _journey_channel(interaction.get("channel"), interaction.get("interaction_type")),
				"status": "current" if index == len(milestones) - 1 else "completed",
			}
		)
	return journey


def _is_journey_milestone(interaction) -> bool:
	"""Keep application/lifecycle milestones out of the general activity feed."""
	if interaction.get("reference_doctype") == "FCRM Note":
		return False
	interaction_type = str(interaction.get("interaction_type") or "").strip().upper()
	if _fold(interaction_type) in JOURNEY_EXCLUDED_ACTIVITY_TYPES:
		return False
	semantics = resolve_interaction_type(interaction_type)
	if semantics and semantics.get("evidence_kind") in JOURNEY_MILESTONE_EVIDENCE_KINDS:
		return True

	legacy_text = _fold(
		" ".join(
			str(interaction.get(field) or "")
			for field in ("summary", "next_follow_up_action")
		)
	)
	return any(term in legacy_text for term in JOURNEY_MILESTONE_TERMS)


def _engagement(interactions):
	return [
		{
			"label": "Tổng tương tác",
			"value": str(len(interactions)),
			"level": "Cao" if len(interactions) >= 5 else "Trung bình" if interactions else "Thấp",
		},
		{
			"label": "Tương tác gần nhất",
			"value": _relative_time(interactions[0].get("interaction_datetime")) if interactions else "",
			"level": "Cao" if interactions else "Thấp",
		},
	]


def _application_items(applications):
	return [
		{
			"label": application.get("major") or "Hồ sơ xét tuyển",
			"value": application.get("status"),
			"status": "success"
			if application.get("status") in {"Accepted", "Enrolled"}
			else "warning"
			if application.get("status") in {"Draft", "Under Review"}
			else "primary",
		}
		for application in applications
	]


def _key_values(values):
	return [{"label": label, "value": str(value)} for label, value in values if value not in (None, "")]


def _grade_label(row) -> str | None:
	grade = row.get("current_grade")
	if grade:
		return f"Lớp {grade}"
	return row.get("study_stage")


def _display_date(value) -> str | None:
	if not value:
		return None
	try:
		return frappe.utils.get_datetime(value).strftime("%d/%m/%Y")
	except (AttributeError, TypeError, ValueError):
		return str(value)


def _insight_summary(stage: str | None, score: float | int | None) -> str:
	if stage and score is not None:
		return f"Hồ sơ đang ở giai đoạn {stage}, điểm tín hiệu {score}."
	return "Chưa đủ dữ liệu để tạo nhận định."


def _source_group(source: str) -> str:
	value = _fold(source)
	if any(token in value for token in ("gioi thieu", "referral", "alumni")):
		return "Giới thiệu"
	if any(token in value for token in ("event", "career", "open day", "hoi thao", "su kien")):
		return "Thực địa"
	if any(token in value for token in ("ads", "facebook", "google", "quang cao")):
		return "Trực tuyến qua quảng cáo"
	return "Trực tuyến chủ động"


def _journey_channel(channel: str | None, interaction_type: str | None = None) -> str:
	value = _fold(channel or interaction_type or "")
	if "zalo" in value:
		return "Zalo"
	if "call" in value or "goi" in value:
		return "Cuộc gọi"
	if "event" in value or "su kien" in value:
		return "Sự kiện"
	if "ho so" in value or "application" in value:
		return "Hồ sơ"
	return "Website"


def _is_confirmed_high_intent(row) -> bool:
	return row.get("assessment_status") == "confirmed" and _fold(row.get("interest_level")) in {"high", "cao"}


def _rate(numerator: int, denominator: int) -> float:
	return round(100 * numerator / denominator, 1) if denominator else 0.0


def _percent_delta(current: int, previous: int) -> float | None:
	return round(100 * (current - previous) / previous, 1) if previous else None


def _total_pages(total: int, page_size: int) -> int:
	return (total + page_size - 1) // page_size if total else 0


def _initials(name: str | None) -> str | None:
	words = [word for word in re.split(r"\s+", str(name or "").strip()) if word]
	return "".join(word[0] for word in words[-2:]).upper() or None


def _number(value):
	if value in (None, ""):
		return None
	try:
		parsed = float(value)
	except (TypeError, ValueError):
		return None
	return int(parsed) if parsed.is_integer() else round(parsed, 2)


def _relative_time(value) -> str | None:
	if not value:
		return None
	try:
		return frappe.utils.pretty_date(value)
	except (AttributeError, TypeError, ValueError):
		return _as_iso(value)


def _local_datetime(value):
	if not value:
		return None
	try:
		parsed = frappe.utils.get_datetime(value)
		if parsed.tzinfo is None:
			return parsed.replace(tzinfo=LOCAL_TIMEZONE)
		return parsed.astimezone(LOCAL_TIMEZONE)
	except (TypeError, ValueError, AttributeError):
		return None


def _as_iso(value) -> str | None:
	parsed = _local_datetime(value)
	return parsed.isoformat(timespec="seconds") if parsed else str(value) if value else None


def _province_label(value: str | None) -> str | None:
	if not value:
		return None
	if _table_exists("CRM Province"):
		label = frappe.db.get_value("CRM Province", value, "province_name")
		return label or value
	return value


def _fold(value: Any) -> str:
	text = unicodedata.normalize("NFD", str(value or ""))
	return "".join(char for char in text if unicodedata.category(char) != "Mn").casefold()


def _slug(value: Any) -> str:
	return re.sub(r"[^a-z0-9]+", "-", _fold(value)).strip("-")


def _table_exists(doctype: str) -> bool:
	try:
		return bool(frappe.db.table_exists(doctype))
	except (AttributeError, frappe.DoesNotExistError):
		return False


def _exists(doctype: str, value) -> bool:
	try:
		return bool(frappe.db.exists(doctype, value))
	except (AttributeError, frappe.DoesNotExistError):
		return False


def _require_access():
	"""Require an authenticated session with Student read permission.

	The Student detail and operational queries deliberately use Frappe's
	permission-aware ``get_list``/``has_permission`` APIs. The list endpoint has
	a separate, explicit Sale read projection so Sale can inspect its team and
	pool before assigning; direct CRUD/detail scope remains assigned-only.
	"""
	user = getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		_raise_api_error(
			"UNAUTHENTICATED",
			"Bạn cần đăng nhập để truy cập dữ liệu học sinh.",
			frappe.AuthenticationError,
			401,
		)

	try:
		frappe.has_permission("CRM Student", "read", user=user, throw=True)
	except frappe.PermissionError:
		# A Group leader may not have a child Team Membership row. The existing
		# dashboard projection still grants the narrower Group-level read scope.
		if get_student_list_read_condition(user) not in (None, "1=0"):
			return
		_raise_api_error(
			"FORBIDDEN",
			"Bạn không có quyền đọc dữ liệu học sinh.",
			frappe.PermissionError,
			403,
		)


def _raise_api_error(code: str, message: str, exception, status: int):
	try:
		if getattr(frappe, "local", None) and isinstance(getattr(frappe.local, "response", None), dict):
			frappe.local.response["error"] = {"code": code, "message": message}
			frappe.local.response["http_status_code"] = status
	except (AttributeError, TypeError):
		pass
	frappe.throw(_(message), exception)
