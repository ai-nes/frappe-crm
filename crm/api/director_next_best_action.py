"""Director snapshot and command API for the Next Best Action workspace.

The endpoint is a bounded read model over canonical CRM aggregates. It does
not create recommendations, infer AI facts, or mutate Student lifecycle state.
Mutations are translated to the Phase 6 recommendation decision service so
CAS, idempotency, audit and outbox rules remain in one place.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import frappe

from crm.api.director_admission_funnel import (
	_load_territory_geographies,
	_student_matches_geography,
)
from crm.api.director_admission_funnel import (
	_normalize_scope as _normalize_funnel_scope,
)
from crm.api.director_admission_funnel import (
	_resolve_admission_year as _resolve_funnel_admission_year,
)
from crm.api.director_school_common import raise_api_error as _common_raise_api_error
from crm.api.director_school_common import require_director_access
from crm.fcrm.student_decision import StudentDecisionError, decide_recommendation

LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
POLICY_VERSION = "action-policy-2026.08"
RESPONSE_WINDOW_HOURS = 8
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
OUTCOME_PERIODS = {"30d": 30}
QUEUE_STATES = {"new", "acknowledged", "accepted", "deferred"}
ACTIVE_SLA_STATUSES = {"open", "warned", "breached", "escalated"}
PROGRESSED_OUTCOMES = {"INTEREST_INCREASED", "APPLICATION_STARTED", "APPLICATION_COMPLETED"}

RECOMMENDATION_FIELDS = [
	"name",
	"student",
	"rule_key",
	"policy_version",
	"priority",
	"status",
	"expires_at",
	"created_at",
	"creation",
	"recommended_action",
	"recommended_timing",
	"cta",
	"talking_points",
	"reason",
	"evidence",
	"decision_revision",
	"decision_at",
	"decision_actor",
	"revisit_at",
]
STUDENT_FIELDS = [
	"name",
	"student_name",
	"admission_year",
	"high_school",
	"major",
	"branch",
	"province",
	"ward",
	"owner_staff",
	"assigned_to",
]
ACTION_FIELDS = [
	"name",
	"student",
	"recommendation",
	"origin",
	"action_type",
	"state",
	"execution_status",
	"priority",
	"due_at",
	"action_owner",
	"accepted_at",
	"completed_at",
	"outcome_code",
	"created_at",
	"creation",
]
ASSESSMENT_FIELDS = [
	"student",
	"status",
	"assessed_at",
	"creation",
	"model_version",
	"enrollment_probability",
	"interest_confidence",
	"fit_confidence",
	"barrier_confidence",
	"recommendation",
]
INTERACTION_FIELDS = [
	"name",
	"student",
	"interaction_type",
	"interaction_datetime",
	"channel",
	"outcome",
	"creation",
]
SLA_FIELDS = [
	"name",
	"student",
	"status",
	"owner_staff",
	"warning_at",
	"breach_at",
	"opened_at",
	"responded_at",
	"created_at",
	"creation",
]

ACTION_LABELS = {
	"CALL": "Gọi phụ huynh",
	"PARENT_CONTACT": "Gọi phụ huynh",
	"COUNSELING": "Tư vấn học bổng",
	"EVENT_INVITE": "Mời tham quan cơ sở",
	"HANDOFF": "Chuyển người phụ trách",
	"EMAIL": "Gửi lại thông tin",
	"MESSAGE": "Gửi lại thông tin",
	"APPLICATION_SUPPORT": "Hỗ trợ hồ sơ",
	"DOCUMENT_REQUEST": "Bổ sung hồ sơ",
	"MEETING": "Đặt lịch tư vấn",
	"CAMPUS_VISIT": "Mời tham quan cơ sở",
}
RECOMMENDATION_LABELS = {
	"WAIT": "Theo dõi hồ sơ",
	"CALL": "Gọi phụ huynh",
	"EMAIL": "Gửi email tư vấn",
	"FOLLOW_UP": "Theo dõi hồ sơ",
	"EVENT_INVITE": "Mời tham quan cơ sở",
	"COUNSELING": "Tư vấn học bổng",
	"HANDOFF": "Chuyển người phụ trách",
}
CONTROL_POLICY_ROWS = [
	{
		"level": "automatic",
		"label": "Tự động",
		"actionTypes": ["reminder", "internal-update"],
		"detail": "Nhắc lịch và cập nhật nội bộ",
		"execution": "system",
	},
	{
		"level": "review",
		"label": "Cần kiểm tra",
		"actionTypes": ["assign", "schedule", "invite"],
		"detail": "Giao việc, đặt lịch, mời sự kiện",
		"execution": "business-rule",
	},
	{
		"level": "approval",
		"label": "Cần duyệt",
		"actionTypes": ["send-message", "change-stage", "bulk-action"],
		"detail": "Gửi nội dung hoặc thay đổi hồ sơ",
		"execution": "human-confirmation",
	},
]


@frappe.whitelist(methods=["GET"])
def get_director_next_best_action(
	admissionYear: str | int | None = None,
	scope: str = "all",
	queueFilter: str = "all",
	page: str | int = DEFAULT_PAGE,
	pageSize: str | int = DEFAULT_PAGE_SIZE,
	outcomePeriod: str = "30d",
) -> dict[str, Any]:
	"""Return one consistent, permission-filtered Director snapshot."""
	access = require_director_access()
	admission_year = _resolve_funnel_admission_year(admissionYear)
	scope_context = _normalize_funnel_scope(scope)
	_authorize_scope(scope_context, access)
	queue_filter = _parse_enum(queueFilter, "queueFilter", {"all", "urgent"}, "all")
	period = _parse_enum(outcomePeriod, "outcomePeriod", OUTCOME_PERIODS, "30d")
	page_number = _parse_integer(page, "page", minimum=1, maximum=None, default=DEFAULT_PAGE)
	page_size = _parse_integer(
		pageSize, "pageSize", minimum=1, maximum=MAX_PAGE_SIZE, default=DEFAULT_PAGE_SIZE
	)
	as_of = _now()
	warnings: list[str] = []
	ai_available = _table_exists("CRM Recommendation") and _table_exists("CRM Student Assessment")
	if not ai_available:
		warnings.append("Nguồn recommendation hoặc assessment AI chưa khả dụng; queue được để trống.")

	students = _load_students(admission_year, scope_context, as_of, warnings)
	student_ids = [str(row.get("name")) for row in students if row.get("name")]
	if not student_ids:
		recommendations: list[dict[str, Any]] = []
		actions: list[dict[str, Any]] = []
		assessments: dict[str, dict[str, Any]] = {}
		interactions: list[dict[str, Any]] = []
		sla_attempts: list[dict[str, Any]] = []
	else:
		recommendations = _load_recommendations(student_ids, warnings) if ai_available else []
		actions = _load_actions(student_ids, warnings)
		assessments = _load_latest_assessments(student_ids, warnings) if ai_available else {}
		interactions = _load_interactions(student_ids, warnings)
		sla_attempts = _load_sla_attempts(student_ids, warnings)

	lookups = _load_lookups(students, recommendations, actions, interactions)
	queue = _build_queue(
		recommendations,
		actions,
		students,
		assessments,
		interactions,
		lookups,
		as_of,
		queue_filter=queue_filter,
		page=page_number,
		page_size=page_size,
	)
	sla = _build_sla_overview(
		sla_attempts,
		students,
		actions,
		assessments,
		interactions,
		lookups,
		as_of,
	)
	outcomes = _build_outcomes(recommendations, actions, as_of, period)
	model_versions = sorted(
		{str(row.get("model_version")) for row in assessments.values() if row.get("model_version")}
	)
	policy_versions = sorted(
		{str(row.get("policy_version")) for row in recommendations if row.get("policy_version")}
	)
	meta_status = "ai_unavailable" if not ai_available else "available" if not warnings else "partial"
	ai_status = (
		"available" if ai_available else "degraded" if _table_exists("CRM Recommendation") else "unavailable"
	)
	return {
		"meta": {
			"admissionYear": _year_number(admission_year),
			"scope": scope_context.get("id") or "all",
			"scopeLabel": scope_context.get("label") or "Toàn bộ cơ sở",
			"asOf": _as_iso(as_of),
			"timezone": "Asia/Ho_Chi_Minh",
			"status": meta_status,
			"aiStatus": ai_status,
			"modelVersion": model_versions[0] if len(model_versions) == 1 else None,
			"policyVersion": policy_versions[0] if len(policy_versions) == 1 else POLICY_VERSION,
			"warnings": warnings or None,
		},
		"queue": queue,
		"sla": sla,
		"outcomes": outcomes,
		"controlPolicy": {"version": POLICY_VERSION, "rows": CONTROL_POLICY_ROWS},
	}


@frappe.whitelist(methods=["POST"])
def apply_action_command(
	actionId: str | None = None,
	command: str | None = None,
	assigneeId: str | None = None,
	deferUntil: str | None = None,
	reason: str | None = None,
	expectedVersion: int | str | None = None,
	idempotencyKey: str | None = None,
	**kwargs: Any,
) -> dict[str, Any]:
	"""Apply one Director queue command through the Phase 6 service."""
	access = require_director_access()
	payload = _merge_command_payload(
		{
			"actionId": actionId,
			"command": command,
			"assigneeId": assigneeId,
			"deferUntil": deferUntil,
			"reason": reason,
			"expectedVersion": expectedVersion,
			"idempotencyKey": idempotencyKey,
		},
		kwargs,
	)
	action_id = _required_text(payload.get("actionId"), "actionId")
	command_name = _parse_enum(payload.get("command"), "command", {"assign", "defer", "dismiss"}, None)
	expected_version = _parse_integer(
		payload.get("expectedVersion"), "expectedVersion", minimum=0, maximum=None, default=None
	)
	key = _resolve_idempotency_key(payload.get("idempotencyKey"))
	reason_text = _optional_text(payload.get("reason"), "reason", maximum=2000)
	recommendation = _get_visible_recommendation(action_id)
	as_of = _now()
	_check_expired(recommendation, as_of)

	if command_name == "assign":
		assignee_id = _required_text(payload.get("assigneeId"), "assigneeId")
		assignee_staff = _resolve_assignee_staff(assignee_id)
		due_at = _coerce_datetime(recommendation.get("recommended_timing"))
		if not due_at:
			action = _linked_action(recommendation.name)
			due_at = _coerce_datetime(action.get("due_at")) if action else None
		if not due_at:
			_raise_command_error("INVALID_COMMAND", "Recommendation không có dueAt hợp lệ để giao việc.", 400)
		status = "accepted"
		decision_reason = reason_text
		revisit_at = None
	elif command_name == "defer":
		defer_until_value = payload.get("deferUntil") or _default_defer_until(recommendation, as_of)
		defer_until_dt = _parse_defer_until(defer_until_value, as_of)
		status = "deferred"
		decision_reason = reason_text
		revisit_at = defer_until_dt
	else:
		if not reason_text:
			_raise_command_error("INVALID_COMMAND", "reason là bắt buộc khi bỏ đề xuất.", 400)
		status = "rejected"
		decision_reason = reason_text
		revisit_at = None

	correlation_id = f"director-nba:{key}"
	try:
		result = decide_recommendation(
			name=action_id,
			expected_revision=expected_version,
			status=status,
			idempotency_key=key,
			correlation_id=correlation_id,
			decision_reason=decision_reason,
			due_at=due_at if command_name == "assign" else None,
			assignee_staff=assignee_staff if command_name == "assign" else None,
			revisit_at=revisit_at,
		)
	except StudentDecisionError as exc:
		code = {"STALE_REVISION": "STALE_ACTION_VERSION", "INVALID_STATE": "STALE_ACTION_VERSION"}.get(
			exc.code, exc.code
		)
		_raise_command_error(code, str(exc).split(": ", 1)[-1], _command_status(code))

	state = {"accepted": "assigned", "deferred": "deferred", "rejected": "dismissed"}[status]
	version = int(result.get("revision") or expected_version + 1)
	applied_at = _event_timestamp(result.get("event")) or _now()
	return {
		"actionId": action_id,
		"command": command_name,
		"state": state,
		"version": version,
		"appliedAt": _as_iso(applied_at),
		"deferUntil": _as_iso(revisit_at) if command_name == "defer" else None,
		"replayed": bool(result.get("replayed")),
		"audit": {
			"eventId": result.get("event"),
			"actorId": access.get("user") or frappe.session.user,
			"occurredAt": _as_iso(applied_at),
		},
	}


def _load_students(
	admission_year: str, scope: dict[str, Any], as_of: datetime, warnings: list[str]
) -> list[dict[str, Any]]:
	if not _table_exists("CRM Student"):
		_raise_api_error(
			"DIRECTOR_NEXT_BEST_ACTION_UNAVAILABLE", "Không thể tải dữ liệu hồ sơ tuyển sinh.", 503
		)
	filters: dict[str, Any] = {"admission_year": admission_year}
	if scope.get("branch"):
		filters["branch"] = scope["branch"]
	rows = _fetch_rows(
		"CRM Student", filters=filters, fields=STUDENT_FIELDS, order_by="creation asc, name asc"
	)
	if scope.get("territory"):
		try:
			assignments = _load_territory_geographies(scope["territory"], as_of)
			provinces = _lookup_map("CRM Province", {row.get("province") for row in rows}, "province_name")
			rows = [
				row
				for row in rows
				if any(
					_student_matches_geography(row, assignment, {"provinces": provinces})
					for assignment in assignments
				)
			]
		except frappe.ValidationError:
			raise
		except Exception:
			warnings.append("Không thể xác định phạm vi địa lý của territory.")
	return rows


def _load_recommendations(student_ids: list[str], warnings: list[str]) -> list[dict[str, Any]]:
	if not _table_exists("CRM Recommendation"):
		return []
	return _fetch_rows(
		"CRM Recommendation",
		filters={"student": ["in", student_ids]},
		fields=RECOMMENDATION_FIELDS,
		order_by="worklist_priority_rank asc, worklist_timing_sort asc, creation asc, name asc",
	)


def _load_actions(student_ids: list[str], warnings: list[str]) -> list[dict[str, Any]]:
	if not _table_exists("CRM Action"):
		warnings.append("CRM Action chưa khả dụng; outcome và suggested assignee có thể thiếu.")
		return []
	return _fetch_rows(
		"CRM Action",
		filters={"student": ["in", student_ids]},
		fields=ACTION_FIELDS,
		order_by="creation desc, name desc",
	)


def _load_latest_assessments(student_ids: list[str], warnings: list[str]) -> dict[str, dict[str, Any]]:
	if not _table_exists("CRM Student Assessment"):
		warnings.append("CRM Student Assessment chưa khả dụng; queue AI được để trống.")
		return {}
	rows = _fetch_rows(
		"CRM Student Assessment",
		filters={"student": ["in", student_ids], "status": "confirmed"},
		fields=ASSESSMENT_FIELDS,
		order_by="assessed_at desc, creation desc",
	)
	latest: dict[str, dict[str, Any]] = {}
	for row in rows:
		latest.setdefault(str(row.get("student")), row)
	return latest


def _load_interactions(student_ids: list[str], warnings: list[str]) -> list[dict[str, Any]]:
	if not _table_exists("CRM Interaction"):
		return []
	return _fetch_rows(
		"CRM Interaction",
		filters={"student": ["in", student_ids]},
		fields=INTERACTION_FIELDS,
		order_by="interaction_datetime desc, creation desc, name desc",
	)


def _load_sla_attempts(student_ids: list[str], warnings: list[str]) -> list[dict[str, Any]]:
	if not _table_exists("CRM Student SLA Attempt"):
		warnings.append("CRM Student SLA Attempt chưa khả dụng; SLA được trả về với số liệu rỗng.")
		return []
	return _fetch_rows(
		"CRM Student SLA Attempt",
		filters={"student": ["in", student_ids]},
		fields=SLA_FIELDS,
		order_by="creation desc, name desc",
	)


def _load_lookups(
	students: list[dict[str, Any]],
	recommendations: list[dict[str, Any]],
	actions: list[dict[str, Any]],
	interactions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
	owner_ids = {row.get("owner_staff") or row.get("assigned_to") for row in students}
	owner_ids.update(row.get("action_owner") for row in actions)
	return {
		"schools": _lookup_map(
			"CRM High School", {row.get("high_school") for row in students}, "school_name"
		),
		"majors": _lookup_map("CRM Major", {row.get("major") for row in students}, "major_name"),
		"owners": _lookup_map("CRM Staff", owner_ids, "full_name"),
		"interaction_types": _lookup_map(
			"CRM Term", {row.get("interaction_type") for row in interactions}, "term_name"
		),
	}


def _build_queue(
	recommendations: list[dict[str, Any]],
	actions: list[dict[str, Any]],
	students: list[dict[str, Any]],
	assessments: dict[str, dict[str, Any]],
	interactions: list[dict[str, Any]],
	lookups: dict[str, dict[str, Any]],
	as_of: datetime,
	*,
	queue_filter: str,
	page: int,
	page_size: int,
) -> dict[str, Any]:
	student_by_id = {str(row.get("name")): row for row in students if row.get("name")}
	action_by_recommendation = {
		str(row.get("recommendation")): row for row in actions if row.get("recommendation")
	}
	interactions_by_student = _group_by(interactions, "student")
	all_items: list[dict[str, Any]] = []
	for recommendation in recommendations:
		student_id = str(recommendation.get("student") or "")
		student = student_by_id.get(student_id)
		if not student or recommendation.get("status") not in QUEUE_STATES:
			continue
		expires_at = _coerce_datetime(recommendation.get("expires_at"))
		if expires_at and expires_at <= as_of:
			continue
		linked_action = action_by_recommendation.get(str(recommendation.get("name")))
		if linked_action and linked_action.get("state") in {
			"completed",
			"cancelled",
			"superseded",
			"rejected",
		}:
			continue
		if recommendation.get("status") == "deferred":
			revisit_at = _coerce_datetime(recommendation.get("revisit_at"))
			if revisit_at and revisit_at > as_of:
				continue
		item = _action_dto(
			recommendation,
			student,
			assessments.get(student_id) or {},
			interactions_by_student.get(student_id, []),
			lookups,
			linked_action,
			as_of,
		)
		all_items.append(item)
	all_items.sort(key=_queue_sort_key)
	counts = {
		"all": len(all_items),
		"urgent": sum(item["status"] in {"today", "overdue"} for item in all_items),
		"today": sum(item["status"] == "today" for item in all_items),
		"overdue": sum(item["status"] == "overdue" for item in all_items),
		"soon": sum(item["status"] == "soon" for item in all_items),
	}
	filtered = [item for item in all_items if queue_filter == "all" or item["status"] in {"today", "overdue"}]
	start = (page - 1) * page_size
	page_items = filtered[start : start + page_size]
	return {
		"actions": page_items,
		"counts": counts,
		"pagination": {
			"page": page,
			"pageSize": page_size,
			"total": len(filtered),
			"hasNext": start + page_size < len(filtered),
		},
	}


def _action_dto(
	recommendation: dict[str, Any],
	student: dict[str, Any],
	assessment: dict[str, Any],
	interactions: list[dict[str, Any]],
	lookups: dict[str, dict[str, Any]],
	linked_action: dict[str, Any] | None,
	as_of: datetime,
) -> dict[str, Any]:
	recommendation_code = str(
		recommendation.get("rule_key") or recommendation.get("recommended_action") or "recommendation"
	)
	action_code = str(recommendation.get("recommended_action") or "").upper()
	evidence = _json_value(recommendation.get("evidence"))
	text_evidence = _display_texts(evidence)
	metrics = _evidence_metrics(evidence)
	probability = _number(assessment.get("enrollment_probability"))
	confidence = metrics.get("confidence")
	if confidence is None:
		confidence_values = [
			_number(assessment.get(field))
			for field in ("interest_confidence", "fit_confidence", "barrier_confidence")
			if _number(assessment.get(field)) is not None
		]
		confidence = round(sum(confidence_values) / len(confidence_values), 1) if confidence_values else 0
	due_at = _coerce_datetime((linked_action or {}).get("due_at")) or _coerce_datetime(
		recommendation.get("recommended_timing")
	)
	state = {
		"accepted": "assigned",
		"deferred": "deferred",
		"new": "proposed",
		"acknowledged": "proposed",
	}.get(str(recommendation.get("status")), "proposed")
	if linked_action and linked_action.get("state") in {"accepted", "in-progress", "requires-review"}:
		state = "assigned"
	status = _due_status(due_at, as_of)
	owner_id = (
		(linked_action or {}).get("action_owner") or student.get("owner_staff") or student.get("assigned_to")
	)
	owner_name = lookups.get("owners", {}).get(str(owner_id), owner_id) if owner_id else None
	student_name = str(student.get("student_name") or student.get("name") or "")
	recommendation_label = (
		recommendation.get("cta")
		or assessment.get("recommendation")
		or RECOMMENDATION_LABELS.get(action_code, action_code or "Theo dõi hồ sơ")
	)
	impact = metrics.get("impact") or "Chưa có dữ liệu tác động"
	return {
		"id": recommendation.get("name"),
		"studentId": student.get("name"),
		"studentName": student_name,
		"initials": _initials(student_name),
		"schoolId": student.get("high_school"),
		"school": lookups.get("schools", {}).get(
			str(student.get("high_school")), student.get("high_school") or "Chưa xác định"
		),
		"interest": lookups.get("majors", {}).get(str(student.get("major")), student.get("major")),
		"recommendationCode": recommendation_code,
		"recommendation": _safe_text(recommendation_label),
		"summary": _safe_text(recommendation.get("reason") or ""),
		"dueAt": _as_iso(due_at),
		"dueLabel": _due_label(due_at, as_of),
		"status": status,
		"priority": _priority(recommendation.get("priority")),
		"impact": _safe_text(impact),
		"currentProbability": _bounded_percent(probability),
		"projectedProbability": _bounded_percent(metrics.get("projected_probability")),
		"confidence": _bounded_percent(confidence) or 0,
		"suggestedAssigneeId": owner_id,
		"suggestedAssignee": owner_name,
		"evidence": text_evidence,
		"talkingPoints": _display_texts(_json_value(recommendation.get("talking_points"))),
		"recentActivity": [_activity_dto(row, lookups, as_of) for row in interactions[:5]],
		"controlLevel": "approval" if action_code in {"EMAIL", "MESSAGE", "HANDOFF"} else "review",
		"state": state,
		"generatedAt": _as_iso(
			_coerce_datetime(recommendation.get("created_at") or recommendation.get("creation"))
		)
		or "",
		"expiresAt": _as_iso(_coerce_datetime(recommendation.get("expires_at"))),
		"version": int(recommendation.get("decision_revision") or 0),
	}


def _build_sla_overview(
	attempts: list[dict[str, Any]],
	students: list[dict[str, Any]],
	actions: list[dict[str, Any]],
	assessments: dict[str, dict[str, Any]],
	interactions: list[dict[str, Any]],
	lookups: dict[str, dict[str, Any]],
	as_of: datetime,
) -> dict[str, Any]:
	latest_attempts = _latest_by_student(attempts)
	active = [row for row in latest_attempts.values() if row.get("status") in ACTIVE_SLA_STATUSES]
	bucket_ids = {"within-sla": [], "due-soon": [], "overdue": []}
	for attempt in active:
		bucket_ids[_sla_bucket(attempt, as_of)].append(attempt)
	total_active = len(active)
	status_buckets = [
		{
			"id": "within-sla",
			"label": "Còn trong hạn",
			"count": len(bucket_ids["within-sla"]),
			"share": _share(len(bucket_ids["within-sla"]), total_active),
			"detail": "Có thể xử lý theo lịch hiện tại",
			"tone": "success",
		},
		{
			"id": "due-soon",
			"label": "Sắp đến hạn",
			"count": len(bucket_ids["due-soon"]),
			"share": _share(len(bucket_ids["due-soon"]), total_active),
			"detail": "Còn dưới 60 phút trước mốc phản hồi",
			"tone": "warning",
		},
		{
			"id": "overdue",
			"label": "Đã quá hạn",
			"count": len(bucket_ids["overdue"]),
			"share": _share(len(bucket_ids["overdue"]), total_active),
			"detail": "Cần điều phối ngay",
			"tone": "error",
		},
	]
	if total_active:
		status_buckets[-1]["share"] = round(
			status_buckets[-1]["share"] + 100 - sum(row["share"] for row in status_buckets), 1
		)
	student_by_id = {str(row.get("name")): row for row in students if row.get("name")}
	interactions_by_student = _group_by(interactions, "student")
	actions_by_student = _group_by(actions, "student")
	overdue = bucket_ids["overdue"]
	risk_cases = []
	for attempt in overdue:
		student_id = str(attempt.get("student") or "")
		student = student_by_id.get(student_id) or {}
		assessment = assessments.get(student_id) or {}
		last_activity = _coerce_datetime(
			(interactions_by_student.get(student_id) or [{}])[0].get("interaction_datetime")
		)
		last_activity = last_activity or _coerce_datetime(attempt.get("opened_at"))
		silent_hours = max(0, int((as_of - last_activity).total_seconds() // 3600)) if last_activity else None
		owner_id = attempt.get("owner_staff") or student.get("owner_staff") or student.get("assigned_to")
		probability = _bounded_percent(_number(assessment.get("enrollment_probability")))
		risk_cases.append(
			{
				"studentId": student_id,
				"name": student.get("student_name") or student_id,
				"school": lookups.get("schools", {}).get(
					str(student.get("high_school")), student.get("high_school") or "Chưa xác định"
				),
				"probability": probability,
				"silentForHours": silent_hours,
				"silentFor": _silent_label(silent_hours),
				"ownerId": owner_id,
				"owner": lookups.get("owners", {}).get(str(owner_id), owner_id)
				if owner_id
				else "Chưa phân công",
				"priority": "high"
				if (probability is not None and probability >= 65) or not owner_id
				else "watch",
				"href": f"/director/students/{student_id}",
			}
		)
	risk_cases.sort(
		key=lambda row: (
			row["priority"] != "high",
			-(row["probability"] or -1),
			-(row["silentForHours"] or -1),
		)
	)
	reason_counts = defaultdict(int)
	for attempt in overdue:
		student_id = str(attempt.get("student") or "")
		owner_id = attempt.get("owner_staff") or (student_by_id.get(student_id) or {}).get("owner_staff")
		if not owner_id:
			reason_counts["unassigned"] += 1
		elif not any(
			row.get("state") in {"pending", "accepted", "in-progress", "requires-review", "deferred"}
			for row in actions_by_student.get(student_id, [])
		):
			reason_counts["no-next-step"] += 1
		elif not interactions_by_student.get(student_id):
			reason_counts["data-delayed"] += 1
		else:
			reason_counts["other"] += 1
	risk_reasons = _risk_reason_rows(reason_counts, len(overdue))
	terminal = [row for row in attempts if row.get("responded_at")]
	on_time = sum(
		1
		for row in terminal
		if _coerce_datetime(row.get("breach_at"))
		and _coerce_datetime(row.get("responded_at")) <= _coerce_datetime(row.get("breach_at"))
	)
	return {
		"responseWindowHours": RESPONSE_WINDOW_HOURS,
		"onTimeRate": round(on_time / len(terminal) * 100, 1) if terminal else None,
		"onTimeDetail": "Mốc phản hồi 8 giờ làm việc",
		"statusBuckets": status_buckets,
		"riskCases": risk_cases[:10],
		"riskReasons": risk_reasons,
	}


def _build_outcomes(
	recommendations: list[dict[str, Any]], actions: list[dict[str, Any]], as_of: datetime, period: str
) -> dict[str, Any]:
	start = as_of - timedelta(days=OUTCOME_PERIODS[period])
	rows: dict[str, dict[str, Any]] = {}
	action_by_recommendation = {
		str(row.get("recommendation")): row for row in actions if row.get("recommendation")
	}
	for recommendation in recommendations:
		code = _canonical_action_code(recommendation.get("recommended_action"))
		if not code:
			continue
		row = rows.setdefault(code, _outcome_row(code))
		created_at = _event_datetime(recommendation, "created_at", "creation")
		if _in_period(created_at, start, as_of):
			row["submitted"] += 1
		if recommendation.get("status") == "accepted":
			accepted_at = _event_datetime(recommendation, "decision_at") or created_at
			if _in_period(accepted_at, start, as_of):
				row["accepted"] += 1
		linked_action = action_by_recommendation.get(str(recommendation.get("name")))
		if linked_action:
			_count_action_outcome(row, linked_action, start, as_of)
	for action in actions:
		if action.get("recommendation") or str(action.get("origin") or "") not in {"ai", "system"}:
			continue
		code = _canonical_action_code(action.get("action_type"))
		if not code:
			continue
		row = rows.setdefault(code, _outcome_row(code))
		created_at = _event_datetime(action, "created_at", "creation")
		if _in_period(created_at, start, as_of):
			row["submitted"] += 1
		accepted_at = _event_datetime(action, "accepted_at") or created_at
		if action.get("state") in {"accepted", "in-progress", "completed"} and _in_period(
			accepted_at, start, as_of
		):
			row["accepted"] += 1
		_count_action_outcome(row, action, start, as_of)
	for row in rows.values():
		row["transitionRate"] = (
			round(row["progressed"] / row["executed"] * 100, 1) if row["executed"] else None
		)
	return {
		"period": period,
		"rows": sorted(
			rows.values(),
			key=lambda row: (row["transitionRate"] is None, -(row["transitionRate"] or 0), row["id"]),
		),
	}


def _count_action_outcome(
	row: dict[str, Any], action: dict[str, Any], start: datetime, as_of: datetime
) -> None:
	completed_at = _event_datetime(action, "completed_at")
	if action.get("execution_status") == "completed" and not completed_at:
		completed_at = _event_datetime(action, "creation")
	if not _in_period(completed_at, start, as_of):
		return
	row["executed"] += 1
	if str(action.get("outcome_code") or "") in PROGRESSED_OUTCOMES:
		row["progressed"] += 1


def _outcome_row(code: str) -> dict[str, Any]:
	return {
		"id": code.lower().replace("_", "-"),
		"label": ACTION_LABELS.get(code, code.replace("_", " ").title()),
		"submitted": 0,
		"accepted": 0,
		"executed": 0,
		"progressed": 0,
		"transitionRate": None,
	}


def _canonical_action_code(value: Any) -> str | None:
	code = str(value or "").strip().upper()
	return code if code in ACTION_LABELS or code in {"WAIT", "FOLLOW_UP"} else None


def _merge_command_payload(values: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
	body: dict[str, Any] = {}
	try:
		request_json = frappe.request.get_json(silent=True)
		if isinstance(request_json, dict):
			body = request_json
	except Exception:
		body = {}
	result = {}
	for key, value in values.items():
		result[key] = value if value not in (None, "") else body.get(key)
	for key in values:
		if result.get(key) in (None, "") and key in kwargs:
			result[key] = kwargs[key]
	return result


def _get_visible_recommendation(name: str):
	try:
		doc = frappe.get_doc("CRM Recommendation", name)
	except (frappe.DoesNotExistError, frappe.PermissionError):
		_raise_command_error("ACTION_NOT_FOUND", "Không tìm thấy đề xuất.", 404)
	if not doc.has_permission("read"):
		_raise_command_error("ACTION_NOT_FOUND", "Không tìm thấy đề xuất.", 404)
	return doc


def _linked_action(recommendation_name: str):
	if not _table_exists("CRM Action"):
		return None
	rows = frappe.get_list(
		"CRM Action",
		filters={"recommendation": recommendation_name},
		fields=["name", "due_at", "action_owner", "state"],
		order_by="creation desc, name desc",
		limit_page_length=1,
	)
	return dict(rows[0]) if rows else None


def _resolve_assignee_staff(value: str) -> str:
	rows = frappe.get_list(
		"CRM Staff", filters={"name": value, "is_active": 1}, fields=["name"], limit_page_length=1
	)
	if rows:
		return str(rows[0].get("name"))
	rows = frappe.get_list(
		"CRM Staff", filters={"user": value, "is_active": 1}, fields=["name"], limit_page_length=1
	)
	if rows:
		return str(rows[0].get("name"))
	_raise_command_error("INVALID_COMMAND", "assigneeId không trỏ tới CRM Staff hợp lệ.", 400)
	return ""


def _check_expired(recommendation, as_of: datetime) -> None:
	expires_at = _coerce_datetime(recommendation.get("expires_at"))
	if expires_at and expires_at <= as_of:
		_raise_command_error("ACTION_EXPIRED", "Đề xuất đã hết hạn và cần được tạo lại.", 409)


def _default_defer_until(recommendation, as_of: datetime) -> datetime:
	base = _coerce_datetime(recommendation.get("created_at") or recommendation.get("creation"))
	expires_at = _coerce_datetime(recommendation.get("expires_at"))
	if expires_at and expires_at > as_of:
		candidate = expires_at - timedelta(hours=1)
		if candidate > as_of:
			return candidate
	if not base or base + timedelta(days=1) <= as_of:
		_raise_command_error("INVALID_DEFER_UNTIL", "Không thể áp dụng thời điểm trì hoãn mặc định.", 422)
	return base + timedelta(days=1)


def _parse_defer_until(value: Any, as_of: datetime) -> datetime:
	parsed = _coerce_datetime(value)
	if not parsed or not _has_timezone(value):
		_raise_command_error("INVALID_DEFER_UNTIL", "deferUntil phải là ISO-8601 có timezone.", 422)
	if parsed <= as_of or parsed > as_of + timedelta(days=30):
		_raise_command_error("INVALID_DEFER_UNTIL", "deferUntil phải nằm trong 30 ngày tới.", 422)
	return parsed


def _has_timezone(value: Any) -> bool:
	if isinstance(value, datetime):
		return value.tzinfo is not None and value.utcoffset() is not None
	text = str(value or "").strip()
	return bool(re.search(r"(?:Z|[+-]\d{2}:?\d{2})$", text, flags=re.IGNORECASE))


def _resolve_idempotency_key(value: Any) -> str:
	body_key = _optional_text(value, "idempotencyKey", maximum=140)
	header_key = None
	try:
		header_key = frappe.get_request_header("Idempotency-Key")
	except Exception:
		try:
			header_key = frappe.request.headers.get("Idempotency-Key")
		except Exception:
			header_key = None
	header_key = _optional_text(header_key, "Idempotency-Key", maximum=140)
	if body_key and header_key and body_key != header_key:
		_raise_command_error("INVALID_COMMAND", "idempotencyKey không khớp Idempotency-Key.", 400)
	key = body_key or header_key
	if not key:
		_raise_command_error("INVALID_COMMAND", "Idempotency-Key là bắt buộc.", 400)
	return key


def _event_timestamp(event_name: str | None) -> datetime | None:
	if not event_name or not _table_exists("CRM Student Decision Event"):
		return None
	return _coerce_datetime(frappe.db.get_value("CRM Student Decision Event", event_name, "occurred_at"))


def _authorize_scope(scope: dict[str, Any], access: dict[str, Any]) -> None:
	if (
		scope.get("id") == "all"
		or access.get("user") == "Administrator"
		or access.get("roleState") == "system_manager"
	):
		return
	staff = frappe.db.get_value(
		"CRM Staff",
		{"user": access.get("user"), "is_active": 1},
		["campus", "territory"],
		as_dict=True,
	)
	if (
		not staff
		or (scope.get("branch") and staff.get("campus") != scope.get("branch"))
		or (scope.get("territory") and staff.get("territory") != scope.get("territory"))
	):
		_raise_api_error("FORBIDDEN", "Scope không nằm trong phạm vi được cấp quyền.", 403)


def _fetch_rows(
	doctype: str, *, filters: dict[str, Any], fields: list[str], order_by: str | None = None
) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	start = 0
	while True:
		query: dict[str, Any] = {
			"filters": filters,
			"fields": fields,
			"limit_start": start,
			"limit_page_length": 5000,
		}
		if order_by:
			query["order_by"] = order_by
		try:
			batch = frappe.get_list(doctype, **query)
		except Exception:
			_raise_api_error("DIRECTOR_NEXT_BEST_ACTION_UNAVAILABLE", "Không thể tải snapshot Director.", 503)
		rows.extend(dict(row) for row in batch)
		if len(batch) < 5000:
			return rows
		start += len(batch)


def _lookup_map(doctype: str, names: set[Any], label_field: str) -> dict[str, str]:
	keys = [str(name) for name in names if name]
	if not keys or not _table_exists(doctype):
		return {}
	try:
		rows = frappe.get_list(
			doctype, filters={"name": ["in", keys]}, fields=["name", label_field], limit_page_length=0
		)
	except Exception:
		return {}
	return {str(row.get("name")): str(row.get(label_field) or row.get("name")) for row in rows}


def _table_exists(doctype: str) -> bool:
	try:
		return bool(frappe.db.table_exists(doctype))
	except Exception:
		return False


def _latest_by_student(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
	latest: dict[str, dict[str, Any]] = {}
	for row in rows:
		student = str(row.get("student") or "")
		if student:
			latest.setdefault(student, row)
	return latest


def _group_by(rows: list[dict[str, Any]], field: str) -> dict[str, list[dict[str, Any]]]:
	result: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for row in rows:
		if row.get(field):
			result[str(row[field])].append(row)
	return result


def _activity_dto(row: dict[str, Any], lookups: dict[str, dict[str, Any]], as_of: datetime) -> dict[str, Any]:
	occurred_at = _coerce_datetime(row.get("interaction_datetime"))
	label = (
		lookups.get("interaction_types", {}).get(str(row.get("interaction_type")))
		or row.get("channel")
		or row.get("outcome")
		or "Hoạt động CRM"
	)
	return {
		"id": row.get("name"),
		"label": _safe_text(label),
		"occurredAt": _as_iso(occurred_at) or "",
		"time": _activity_time_label(occurred_at, as_of),
	}


def _queue_sort_key(item: dict[str, Any]) -> tuple[int, datetime, int, str]:
	return (
		{"overdue": 0, "today": 1, "soon": 2}.get(item.get("status"), 3),
		_coerce_datetime(item.get("dueAt")) or datetime.max.replace(tzinfo=LOCAL_TIMEZONE),
		{"high": 0, "medium": 1, "low": 2}.get(item.get("priority"), 3),
		str(item.get("id") or ""),
	)


def _due_status(due_at: datetime | None, as_of: datetime) -> str:
	if not due_at or due_at < as_of:
		return "overdue" if due_at else "soon"
	return "today" if due_at.date() == as_of.date() else "soon"


def _due_label(due_at: datetime | None, as_of: datetime) -> str:
	if not due_at:
		return "Chưa có thời hạn"
	if due_at < as_of:
		days = max(1, math.ceil((as_of - due_at).total_seconds() / 86400))
		return f"Quá hạn {days} ngày"
	if due_at.date() == as_of.date():
		return "Xử lý hôm nay"
	days = max(1, math.ceil((due_at - as_of).total_seconds() / 86400))
	return f"Trong {days} ngày"


def _sla_bucket(attempt: dict[str, Any], as_of: datetime) -> str:
	status = str(attempt.get("status") or "")
	if status in {"breached", "escalated"} or (
		_coerce_datetime(attempt.get("breach_at")) and _coerce_datetime(attempt.get("breach_at")) <= as_of
	):
		return "overdue"
	if status == "warned" or (
		_coerce_datetime(attempt.get("warning_at")) and _coerce_datetime(attempt.get("warning_at")) <= as_of
	):
		return "due-soon"
	return "within-sla"


def _risk_reason_rows(counts: dict[str, int], denominator: int) -> list[dict[str, Any]]:
	labels = {
		"unassigned": ("Thiếu người phụ trách", "Tập trung ở đội có tải cao"),
		"no-next-step": ("Chưa có bước tiếp theo", "Đã liên hệ nhưng chưa ghi nhận kết quả"),
		"data-delayed": ("Dữ liệu thiếu hoặc trễ", "Nguồn chưa đồng bộ xong"),
		"other": ("Cần kiểm tra thêm", "Chưa phân loại được nguyên nhân từ dữ liệu hiện có"),
	}
	rows = []
	for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
		if count <= 0:
			continue
		label, detail = labels[key]
		rows.append(
			{"id": key, "label": label, "percentage": round(count / denominator * 100, 1), "detail": detail}
		)
	if rows:
		rows[-1]["percentage"] = round(
			rows[-1]["percentage"] + 100 - sum(row["percentage"] for row in rows), 1
		)
	return rows


def _share(numerator: int, denominator: int) -> float:
	return round(numerator / denominator * 100, 1) if denominator else 0.0


def _silent_label(hours: int | None) -> str:
	if hours is None:
		return "Chưa xác định"
	if hours < 24:
		return f"{hours} giờ"
	return f"{max(1, hours // 24)} ngày"


def _activity_time_label(value: datetime | None, as_of: datetime) -> str | None:
	if not value:
		return None
	if value.date() == as_of.date():
		return f"Hôm nay, {value:%H:%M}"
	return value.strftime("%d/%m, %H:%M")


def _initials(value: str) -> str:
	parts = [part for part in re.split(r"\s+", value.strip()) if part]
	return "".join(part[0] for part in parts[-2:]).upper() if parts else "?"


def _priority(value: Any) -> str:
	return (
		str(value or "medium").lower()
		if str(value or "medium").lower() in {"high", "medium", "low"}
		else "medium"
	)


def _evidence_metrics(value: Any) -> dict[str, Any]:
	objects = (
		[value]
		if isinstance(value, dict)
		else [item for item in value if isinstance(item, dict)]
		if isinstance(value, list)
		else []
	)
	result: dict[str, Any] = {}
	aliases = {
		"impact": ("impact", "impact_text"),
		"confidence": ("confidence",),
		"projected_probability": ("projected_probability", "projectedProbability"),
	}
	for target, keys in aliases.items():
		for obj in objects:
			for key in keys:
				if obj.get(key) not in (None, ""):
					result[target] = obj[key]
					break
			if target in result:
				break
	return result


def _display_texts(value: Any) -> list[str]:
	value = _json_value(value)
	if isinstance(value, str):
		return [_safe_text(value)] if value.strip() else []
	if isinstance(value, dict):
		for key in ("display", "text", "label", "description"):
			if value.get(key):
				return [_safe_text(value[key])]
		for key in ("items", "evidence", "values"):
			if isinstance(value.get(key), list):
				return _display_texts(value[key])
		return []
	if isinstance(value, list):
		result = []
		for item in value:
			result.extend(_display_texts(item))
		return list(dict.fromkeys(result))
	return []


def _safe_text(value: Any) -> str:
	text = str(value).strip()
	text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[đã ẩn email]", text)
	return re.sub(r"(?<!\d)(?:\+?\d[\d .()-]{7,}\d)(?!\d)", "[đã ẩn số điện thoại]", text)


def _json_value(value: Any) -> Any:
	if not isinstance(value, str):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return value


def _event_datetime(row: dict[str, Any], *fields: str) -> datetime | None:
	for field in fields:
		value = _coerce_datetime(row.get(field))
		if value:
			return value
	return None


def _in_period(value: datetime | None, start: datetime, end: datetime) -> bool:
	return bool(value and start <= value <= end)


def _coerce_datetime(value: Any) -> datetime | None:
	if not value:
		return None
	try:
		parsed = frappe.utils.get_datetime(value)
	except (AttributeError, TypeError, ValueError, OverflowError):
		return None
	if not parsed:
		return None
	if parsed.tzinfo is None:
		return parsed.replace(tzinfo=LOCAL_TIMEZONE)
	return parsed.astimezone(LOCAL_TIMEZONE)


def _as_iso(value: Any) -> str | None:
	parsed = value if isinstance(value, datetime) else _coerce_datetime(value)
	return parsed.isoformat(timespec="seconds") if parsed else None


def _now() -> datetime:
	return _coerce_datetime(frappe.utils.now_datetime()) or datetime.now(LOCAL_TIMEZONE)


def _year_number(value: Any) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		return 0


def _number(value: Any) -> float | None:
	try:
		return float(value)
	except (TypeError, ValueError):
		return None


def _bounded_percent(value: Any) -> float | None:
	number = _number(value)
	return round(min(100, max(0, number)), 1) if number is not None else None


def _required_text(value: Any, field: str) -> str:
	text = str(value or "").strip()
	if not text or len(text) > 140:
		_raise_command_error("INVALID_COMMAND", f"{field} không hợp lệ.", 400)
	return text


def _optional_text(value: Any, field: str, *, maximum: int) -> str | None:
	if value in (None, ""):
		return None
	text = str(value).strip()
	if len(text) > maximum:
		_raise_command_error("INVALID_COMMAND", f"{field} không hợp lệ.", 400)
	return text or None


def _parse_enum(value: Any, field: str, allowed: set[str], default: str | None) -> str:
	text = default if value in (None, "") else str(value).strip().lower()
	if text not in allowed:
		_raise_api_error(
			"INVALID_QUERY" if field != "command" else "INVALID_COMMAND", f"{field} không hợp lệ.", 400
		)
	return str(text)


def _parse_integer(value: Any, field: str, *, minimum: int, maximum: int | None, default: int | None) -> int:
	if value in (None, "") and default is not None:
		return default
	if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value or "").strip()):
		_raise_api_error(
			"INVALID_QUERY" if field not in {"expectedVersion"} else "INVALID_COMMAND",
			f"{field} không hợp lệ.",
			400,
		)
	number = int(value)
	if number < minimum or (maximum is not None and number > maximum):
		_raise_api_error(
			"INVALID_QUERY" if field not in {"expectedVersion"} else "INVALID_COMMAND",
			f"{field} không hợp lệ.",
			400,
		)
	return number


def _command_status(code: str) -> int:
	return {
		"UNAUTHORIZED": 401,
		"FORBIDDEN": 403,
		"OUT_OF_SCOPE": 404,
		"STALE_REVISION": 409,
		"STALE_ACTION_VERSION": 409,
		"ACTION_EXPIRED": 409,
		"IDEMPOTENCY_KEY_REUSED": 409,
		"INVALID_STATE": 409,
		"CONTRACT_UNAVAILABLE": 503,
		"OUTBOX_DISABLED": 503,
	}.get(code, 400)


def _raise_command_error(code: str, message: str, status: int) -> None:
	_raise_api_error(code, message, status)


def _raise_api_error(code: str, message: str, status: int) -> None:
	exception = {
		401: frappe.AuthenticationError,
		403: frappe.PermissionError,
		404: frappe.DoesNotExistError,
	}.get(status, frappe.ValidationError)
	_common_raise_api_error(code, message, exception, status)


__all__ = ["apply_action_command", "get_director_next_best_action"]
