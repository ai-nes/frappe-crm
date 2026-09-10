"""Director and Sales Next Best Action queue projection.

Read-only envelope consumed by ``/director/ai/next-best-action``. The canonical
work item is ``CRM Action Item`` (``origin='ai'``); this module only projects rows
that Frappe permissions already expose to the caller. It never fabricates
probability or SLA percentages — absent data is returned as ``null`` / ``[]``
per ``docs/action-ui-contract.md``.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

import frappe

from crm.api.director_school_common import (
	parse_enum,
	parse_limit,
	raise_api_error,
	require_director_access,
	resolve_admission_year,
)
from crm.api.nba_recommendation_view import recommendation_view

LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
POLICY_VERSION = "action-policy"
RESPONSE_WINDOW_HOURS = 8
DEFAULT_CONFIDENCE = 70

# Every count, rate and outcome projection here describes what already
# happened in the CRM (submitted/accepted/executed Actions); none of it is a
# causal claim that a recommendation caused an outcome or a prediction of a
# future one. Analytics consumers must render this as descriptive telemetry.
METRIC_KIND_OBSERVATIONAL = "observational"
OBSERVATIONAL_METRIC_DISCLAIMER = (
	"Số liệu mô tả trạng thái lịch sử của các Action, không phải xác nhận quan hệ "
	"nhân quả hay dự đoán hiệu quả của đề xuất."
)

# Rows still awaiting or in a sales decision. ``plan_rank`` 2-3 land as
# ``deferred`` (backlog) from the bundle writer and stay visible but de-ranked.
QUEUE_STATES = ("pending", "requires-review", "accepted", "in-progress", "deferred")

_CONTROL_LEVEL_BY_TYPE: dict[str, str] = {
	"DOCUMENT_REQUEST": "automatic",
	"APPLICATION_SUPPORT": "automatic",
	"CALL": "review",
	"COUNSELING": "review",
	"MEETING": "review",
	"EVENT_INVITE": "review",
	"CAMPUS_VISIT": "review",
	"EMAIL": "approval",
	"MESSAGE": "approval",
	"PARENT_CONTACT": "approval",
	"HANDOFF": "approval",
}

STATIC_CONTROL_POLICY: dict[str, Any] = {
	"version": POLICY_VERSION,
	"rows": [
		{
			"level": "automatic",
			"label": "Tự động chuẩn bị",
			"actionTypes": ["DOCUMENT_REQUEST", "APPLICATION_SUPPORT"],
			"detail": "Hệ thống chuẩn bị nội dung hồ sơ, chuyên viên chỉ rà soát.",
			"execution": "system",
		},
		{
			"level": "review",
			"label": "Cần kiểm tra",
			"actionTypes": ["CALL", "COUNSELING", "MEETING", "EVENT_INVITE", "CAMPUS_VISIT"],
			"detail": "Chuyên viên xác nhận nội dung trước khi thực hiện.",
			"execution": "business-rule",
		},
		{
			"level": "approval",
			"label": "Cần phê duyệt",
			"actionTypes": ["EMAIL", "MESSAGE", "PARENT_CONTACT", "HANDOFF"],
			"detail": "Cần người có thẩm quyền phê duyệt trước khi gửi ra ngoài.",
			"execution": "human-confirmation",
		},
	],
}

_STATE_MAP = {
	"pending": "proposed",
	"requires-review": "proposed",
	"accepted": "assigned",
	"in-progress": "assigned",
	"deferred": "deferred",
	"superseded": "dismissed",
	"cancelled": "dismissed",
	"rejected": "dismissed",
	"completed": "expired",
}

_SCOPE_LABELS = {"all": "Toàn bộ cơ sở"}

_ACTION_FIELDS = [
	"name",
	"student",
	"contact",
	"action",
	"action_type",
	"objective",
	"state",
	"priority",
	"plan_rank",
	"due_at",
	"action_owner",
	"source_context_revision",
	"policy_context_version",
	"evidence_references",
	"package_seed",
	"action_revision",
	"decision_revision",
	"creation",
	"modified",
]


@frappe.whitelist(methods=["GET"])
def get_director_next_best_action(
	admissionYear: str | int | None = None,
	scope: str = "all",
	queueFilter: str = "all",
	page: str | int = 1,
	pageSize: str | int = 8,
	outcomePeriod: str = "30d",
) -> dict[str, Any]:
	"""Return the NBA queue within the caller's Student ownership scope.

	Admissions Director/System Manager see the requested admission-year scope;
	Sale and CTV Sale see their own assigned Students; Lead Sale sees the
	team-and-team-pool scope enforced by the shared Student permission policy.
	"""
	access = require_director_access(allow_sales=True)
	scope_value = parse_enum(scope, field="scope", allowed=_SCOPE_LABELS.keys(), default="all")
	queue_filter = parse_enum(queueFilter, field="queueFilter", allowed=("all", "urgent"), default="all")
	page_number = parse_limit(page, field="page", minimum=1, maximum=10_000, default=1)
	page_size = parse_limit(pageSize, field="pageSize", minimum=1, maximum=100, default=8)
	period = parse_enum(outcomePeriod, field="outcomePeriod", allowed=("7d", "30d", "90d"), default="30d")
	year = resolve_admission_year(admissionYear)
	scope_label = _scope_label_for_access(scope_value, access)

	now = frappe.utils.now_datetime()
	student_ids = _students_for_year(year, access)
	warnings: list[str] = []
	rows: list[Any] = []
	filtered: list[Any] = []
	total = 0

	if student_ids is not None:
		base_filters: dict[str, Any] = {"origin": "ai", "state": ["in", list(QUEUE_STATES)]}
		if student_ids:
			base_filters["student"] = ["in", student_ids]
		all_rows = (
			frappe.get_list(
				"CRM Action Item",
				filters=base_filters,
				fields=_ACTION_FIELDS,
				order_by="plan_rank asc, due_at asc, creation desc",
				limit_page_length=0,
			)
			if student_ids
			else []
		)
		if queue_filter == "urgent":
			filtered = [row for row in all_rows if _is_urgent(row, now)]
		else:
			filtered = all_rows
		total = len(filtered)
		start = (page_number - 1) * page_size
		rows = filtered[start : start + page_size]

	lookups = _load_lookups(rows)
	actions = [_map_item(row, lookups, now) for row in rows]
	warnings.append("Độ tin cậy và xác suất chuyển đổi chưa có nguồn dữ liệu định lượng.")

	counts = _counts(filtered, now)
	outcome_rows = _outcomes(student_ids, period, now) if student_ids else []

	return {
		"meta": {
			"admissionYear": int(year),
			"scope": scope_value,
			"scopeLabel": scope_label,
			"asOf": _as_iso(now),
			"timezone": "Asia/Ho_Chi_Minh",
			"status": "available" if actions else "partial",
			"aiStatus": "available",
			"modelVersion": None,
			"policyVersion": POLICY_VERSION,
			"warnings": warnings or None,
			"metricKind": METRIC_KIND_OBSERVATIONAL,
			"metricDisclaimer": OBSERVATIONAL_METRIC_DISCLAIMER,
		},
		"queue": {
			"actions": actions,
			"counts": counts,
			"pagination": {
				"page": page_number,
				"pageSize": page_size,
				"total": total,
				"hasNext": (page_number * page_size) < total,
			},
		},
		"sla": {
			"responseWindowHours": RESPONSE_WINDOW_HOURS,
			"onTimeRate": None,
			"onTimeDetail": f"Mốc phản hồi {RESPONSE_WINDOW_HOURS} giờ làm việc",
			"statusBuckets": _status_buckets(counts),
			"riskCases": [],
			"riskReasons": [],
		},
		"outcomes": {
			"period": period,
			"rows": outcome_rows,
			# Descriptive counts from historical Action state transitions, not a
			# causal or predictive claim about any recommendation's effect.
			"metricKind": METRIC_KIND_OBSERVATIONAL,
		},
		"controlPolicy": STATIC_CONTROL_POLICY,
	}


# --------------------------------------------------------------------------- #
# Evaluation-epoch recommendation read model
# --------------------------------------------------------------------------- #
# Rows written by an ``CRM NBA Evaluation`` commit carry a non-empty
# ``evaluation`` link. They are a review queue of ranked recommendations, not a
# work list: nothing here says a recommendation is assigned, in progress, or
# scheduled. The immutable ``ai_payload`` kernel object is surfaced verbatim.
_RECOMMENDATION_FIELDS = [
	"name",
	"target_id",
	"action",
	"evaluation",
	"ai_payload",
	"recommendation_key",
	"rank",
	"priority",
	"reason",
	"expires_at",
	"lifecycle_status",
	"decision_status",
	"execution_status",
	"recommended_at",
	"creation",
	"explanation",
	"rationale_source",
]

_RECOMMENDATION_LIMIT_MAX = 200
_RECOMMENDATION_LIMIT_DEFAULT = 50


@frappe.whitelist(methods=["GET"])
def get_director_recommendations(
	admissionYear: str | int | None = None,
	limit: str | int = _RECOMMENDATION_LIMIT_DEFAULT,
) -> dict[str, Any]:
	"""Top-N evaluation-epoch recommendations for the admission year, rank-ascending.

	Read-only projection of ``CRM Recommendation`` rows produced by a settled
	``CRM NBA Evaluation``. Legacy rows (no ``evaluation`` link) are never
	returned by this path. Director and the three Sales profiles are allowed;
	``frappe.get_list`` still applies row permissions and the admission-year
	Student scope — access is never widened here.
	"""
	access = require_director_access(allow_sales=True)
	year = resolve_admission_year(admissionYear)
	limit_value = parse_limit(
		limit,
		field="limit",
		minimum=1,
		maximum=_RECOMMENDATION_LIMIT_MAX,
		default=_RECOMMENDATION_LIMIT_DEFAULT,
	)
	now = frappe.utils.now_datetime()
	student_ids = _students_for_year(year, access)

	items: list[dict[str, Any]] = []
	if student_ids:
		rows = frappe.get_list(
			"CRM Recommendation",
			filters={
				"evaluation": ["is", "set"],
				"target_type": "CRM Lead",
				"target_id": ["in", student_ids],
			},
			fields=_RECOMMENDATION_FIELDS,
			order_by="`rank` asc, recommended_at desc, creation asc",
			limit_page_length=limit_value,
		)
		evaluations = _recommendation_evaluations(rows)
		items = [_map_recommendation(row, evaluations) for row in rows]

	return {
		"meta": {
			"admissionYear": int(year),
			"asOf": _as_iso(now),
			"timezone": "Asia/Ho_Chi_Minh",
			"status": "available" if items else "empty",
			"count": len(items),
			"limit": limit_value,
			"metricKind": METRIC_KIND_OBSERVATIONAL,
			"metricDisclaimer": OBSERVATIONAL_METRIC_DISCLAIMER,
		},
		"recommendations": items,
	}


def _recommendation_evaluations(rows: list[Any]) -> dict[str, dict[str, Any]]:
	"""Parent evaluation disposition/status keyed by evaluation id.

	Permission-scoped: an identity that cannot read ``CRM NBA Evaluation`` gets
	an empty map and the projection degrades to ``null`` disposition/status
	rather than leaking the parent row.
	"""
	evaluation_ids = sorted({row.get("evaluation") for row in rows if row.get("evaluation")})
	if not evaluation_ids:
		return {}
	try:
		found = frappe.get_list(
			"CRM NBA Evaluation",
			filters={"name": ["in", evaluation_ids]},
			fields=["name", "disposition", "status"],
			limit_page_length=0,
		)
	except (frappe.DoesNotExistError, frappe.PermissionError):
		return {}
	return {row["name"]: row for row in found}


def _map_recommendation(row: Any, evaluations: dict[str, dict[str, Any]]) -> dict[str, Any]:
	payload = _parse_json(row.get("ai_payload"))
	if not isinstance(payload, dict):
		payload = {}
	explanation = _parse_json(row.get("explanation"))
	if not isinstance(explanation, dict):
		explanation = None
	parent = evaluations.get(row.get("evaluation")) or {}
	view = recommendation_view(
		recommendation_id=row["name"],
		target_type="CRM Lead",
		target_id=row.get("target_id") or None,
		action_code=row.get("action") or None,
		priority=row.get("priority"),
		rank=int(row.get("rank") or 0),
		reason=row.get("reason"),
		explanation=explanation,
		ai_payload=payload,
		expires_at_iso=_as_iso(row.get("expires_at")),
		lifecycle_status=row.get("lifecycle_status"),
		decision_status=row.get("decision_status"),
		execution_status=row.get("execution_status"),
	)
	return {
		**view,
		"recommendationKey": row.get("recommendation_key") or None,
		"studentId": row.get("target_id") or None,
		"actionId": row.get("action") or None,
		# Immutable kernel recommendation object, surfaced verbatim (no key
		# rewriting) so the accept/edit decision flow's identity/diff logic
		# keeps its existing source of truth. Not for display -- use the
		# nested view fields above for that.
		"aiPayload": payload,
		# Grounded, structured explanation (post-decision render); null until
		# the best-effort explanation pass has run for this recommendation.
		"explanation": explanation,
		"explanationSource": row.get("rationale_source") or None,
		"evaluation": {
			"id": row.get("evaluation") or None,
			"disposition": parent.get("disposition") or None,
			"status": parent.get("status") or None,
		},
		"generatedAt": _as_iso(row.get("recommended_at")) or _as_iso(row.get("creation")),
	}


_COMMAND_STATE = {"assign": "assigned", "defer": "deferred", "dismiss": "dismissed"}


@frappe.whitelist(methods=["POST"])
def apply_action_command(
	actionId: str | None = None,
	command: str | None = None,
	assigneeId: str | None = None,
	deferUntil: str | None = None,
	reason: str | None = None,
	expectedVersion: str | int | None = None,
	idempotencyKey: str | None = None,
) -> dict[str, Any]:
	"""Director NBA queue command: assign / defer / dismiss one CRM Action.

	Thin adapter over the governed ``crm.fcrm.student_decision`` primitives. It
	does not write the Action directly and it does not widen authorization — the
	primitive re-checks capability, scope and CAS. ``expectedVersion`` guards the
	client against the queue ``version`` (``decision_revision``) it last saw; the
	primitive still applies its own revision CAS internally.
	"""
	from crm.fcrm.student_decision import (
		DECISION_EVENT,
		StudentDecisionError,
		decide_student_task,
		reassign_action,
	)

	require_director_access()
	action_id = _require(actionId, "actionId")
	command_value = parse_enum(command, field="command", allowed=_COMMAND_STATE.keys())
	key = _require(idempotencyKey, "idempotencyKey")
	if expectedVersion in (None, ""):
		raise_api_error("INVALID_QUERY", "expectedVersion là bắt buộc.", frappe.ValidationError, 400)
	expected_version = int(expectedVersion)
	correlation_id = f"dnba:{key}"

	# ``CRM Action Item`` is the canonical work-item doctype. Keep the legacy
	# ``CRM Action`` lookup as a read/command compatibility boundary for older
	# clients and queued requests that predate the work-item split.
	action_doctype = "CRM Action Item"
	if not frappe.db.exists(action_doctype, action_id):
		if frappe.db.exists("CRM Action", action_id):
			action_doctype = "CRM Action"
		else:
			raise_api_error("ACTION_NOT_FOUND", "Không tìm thấy hành động.", frappe.DoesNotExistError, 404)
	doc = frappe.get_doc(action_doctype, action_id)
	if not doc.has_permission("read"):
		raise_api_error("FORBIDDEN", "Hành động nằm ngoài phạm vi của bạn.", frappe.PermissionError, 403)
	if int(doc.get("decision_revision") or 0) != expected_version:
		raise_api_error(
			"STALE_VERSION", "Hành động đã thay đổi; tải lại trước khi thử lại.", frappe.ValidationError, 409
		)

	replayed = bool(_safe_exists(DECISION_EVENT, {"correlation_id": correlation_id}))

	try:
		if command_value == "assign":
			assignee = _require(assigneeId, "assigneeId")
			reassign_action(
				name=action_id,
				expected_revision=doc.get("action_revision") or 1,
				assignee_staff=assignee,
				idempotency_key=key,
				reason=reason or "Giao việc từ hàng đợi Director NBA.",
				correlation_id=correlation_id,
			)
		else:
			decide_student_task(
				name=action_id,
				expected_revision=doc.get("decision_revision") or 0,
				status="deferred" if command_value == "defer" else "rejected",
				idempotency_key=key,
				correlation_id=correlation_id,
				decision_reason=reason
				or ("Bỏ qua từ hàng đợi Director NBA." if command_value == "dismiss" else None),
				revisit_at=deferUntil or None,
			)
	except StudentDecisionError as exc:
		if exc.code in {"UNAUTHORIZED", "FORBIDDEN", "OUT_OF_SCOPE"}:
			raise_api_error(exc.code, str(exc), frappe.PermissionError, 403)
		status = 409 if exc.code in {"STALE_REVISION", "INVALID_STATE"} else 400
		raise_api_error(exc.code, str(exc), frappe.ValidationError, status)

	fresh = frappe.get_doc(action_doctype, action_id)
	now = frappe.utils.now_datetime()
	return {
		"actionId": action_id,
		"command": command_value,
		"state": _COMMAND_STATE[command_value],
		"version": int(fresh.get("decision_revision") or 0),
		"appliedAt": _as_iso(now),
		"deferUntil": _as_iso(deferUntil) if deferUntil else None,
		"replayed": replayed,
		"audit": {
			"eventId": _latest_event_id(DECISION_EVENT, correlation_id),
			"actorId": frappe.session.user,
			"occurredAt": _as_iso(now),
		},
	}


def _require(value: Any, label: str) -> str:
	if value in (None, "") or not str(value).strip():
		raise_api_error("INVALID_QUERY", f"{label} là bắt buộc.", frappe.ValidationError, 400)
	return str(value).strip()


def _safe_exists(doctype: str, filters: dict[str, Any]) -> bool:
	try:
		return bool(frappe.db.exists(doctype, filters))
	except Exception:
		return False


def _latest_event_id(doctype: str, correlation_id: str) -> str | None:
	try:
		rows = frappe.get_all(
			doctype,
			filters={"correlation_id": correlation_id},
			fields=["name"],
			order_by="creation desc",
			limit_page_length=1,
		)
	except Exception:
		return None
	return rows[0]["name"] if rows else None


def _students_for_year(year: str, access: dict[str, Any] | None = None) -> list[str] | None:
	"""All in-scope student ids for the admission year, or ``None`` when the
	Student doctype is unavailable (keeps the endpoint 200 with an empty queue).

	The Student permission query remains the authoritative scope for every role.
	The explicit owner filter for Sale/CTV Sale makes their personal portfolio
	boundary visible in the query as well; Lead Sale intentionally keeps the
	team-and-team-pool scope supplied by the Student permission policy.
	"""
	filters: dict[str, Any] = {"admission_year": year}
	if access and access.get("profile") in {"sales", "ctv_sale"}:
		user = access.get("user")
		if not user:
			return []
		staff = frappe.db.get_value("CRM Staff", {"user": user}, "name")
		if not staff:
			return []
		filters["owner_staff"] = staff
	try:
		rows = frappe.get_list(
			"CRM Lead",
			filters=filters,
			fields=["name"],
			limit_page_length=0,
		)
	except (frappe.DoesNotExistError, frappe.PermissionError):
		return None
	return [row["name"] for row in rows if row.get("name")]


def _scope_label_for_access(scope: str, access: dict[str, Any]) -> str:
	"""Describe the effective scope without changing the response contract."""
	return {
		"sales": "Hồ sơ được phân công",
		"ctv_sale": "Hồ sơ được phân công",
		"lead_sales": "Team và pool được phân công",
	}.get(access.get("profile"), _SCOPE_LABELS[scope])


def _is_urgent(row: Any, now) -> bool:
	if _priority_of(row) == "high":
		return True
	due = _due_datetime(row)
	return bool(due and due <= now)


def _priority_of(row: Any) -> str:
	rank = row.get("plan_rank") or 0
	if rank == 1:
		return "high"
	if rank == 2:
		return "medium"
	if rank >= 3:
		return "low"
	value = str(row.get("priority") or "medium").lower()
	return value if value in {"high", "medium", "low"} else "medium"


def _due_datetime(row: Any):
	value = row.get("due_at")
	if not value:
		return None
	try:
		return frappe.utils.get_datetime(value)
	except (TypeError, ValueError):
		return None


def _status_of(row: Any, now) -> str:
	due = _due_datetime(row)
	if due is None:
		return "soon"
	if due < now:
		return "overdue"
	end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
	return "today" if due <= end_of_day else "soon"


def _counts(rows: list[Any], now) -> dict[str, int]:
	buckets = {"today": 0, "soon": 0, "overdue": 0}
	urgent = 0
	for row in rows:
		buckets[_status_of(row, now)] += 1
		if _is_urgent(row, now):
			urgent += 1
	return {
		"all": len(rows),
		"urgent": urgent,
		"today": buckets["today"],
		"overdue": buckets["overdue"],
		"soon": buckets["soon"],
	}


def _status_buckets(counts: dict[str, int]) -> list[dict[str, Any]]:
	total = max(counts["all"], 1)
	definition = [
		(
			"within-sla",
			"Còn trong hạn",
			counts["today"] + counts["soon"],
			"Có thể xử lý theo lịch hiện tại",
			"success",
		),
		("due-soon", "Sắp đến hạn", counts["soon"], "Còn dưới mốc phản hồi", "warning"),
		("overdue", "Đã quá hạn", counts["overdue"], "Cần điều phối ngay", "error"),
	]
	return [
		{
			"id": bucket_id,
			"label": label,
			"count": count,
			"share": round(100 * count / total, 1),
			"detail": detail,
			"tone": tone,
		}
		for bucket_id, label, count, detail, tone in definition
	]


def _outcomes(student_ids: list[str], period: str, now) -> list[dict[str, Any]]:
	if not student_ids:
		return []
	days = {"7d": 7, "30d": 30, "90d": 90}[period]
	since = now - timedelta(days=days)
	rows = frappe.get_list(
		"CRM Action Item",
		filters={
			"origin": "ai",
			"student": ["in", student_ids],
			"plan_rank": ["in", [0, 1]],
			"creation": [">=", since],
		},
		fields=["action_type", "state"],
		limit_page_length=0,
	)
	grouped: dict[str, dict[str, int]] = {}
	for row in rows:
		action_type = row.get("action_type") or "UNKNOWN"
		entry = grouped.setdefault(
			action_type, {"submitted": 0, "accepted": 0, "executed": 0, "progressed": 0}
		)
		entry["submitted"] += 1
		state = row.get("state")
		if state in {"accepted", "in-progress", "completed"}:
			entry["accepted"] += 1
		if state == "completed":
			entry["executed"] += 1
			entry["progressed"] += 1
	result = []
	for action_type, entry in sorted(grouped.items()):
		submitted = entry["submitted"]
		result.append(
			{
				"id": _slug(action_type),
				"label": _action_label(action_type),
				"submitted": submitted,
				"accepted": entry["accepted"],
				"executed": entry["executed"],
				"progressed": entry["progressed"],
				"transitionRate": round(100 * entry["progressed"] / submitted, 1) if submitted else None,
			}
		)
	return result


def _load_lookups(rows: list[Any]) -> dict[str, dict[str, Any]]:
	student_ids = [row["student"] for row in rows if row.get("student")]
	owner_ids = [row["action_owner"] for row in rows if row.get("action_owner")]
	students = (
		{
			row["name"]: row
			for row in _get_lookup_rows(
				"CRM Lead",
				filters={"name": ["in", student_ids]},
				fields=["name", "student_name", "high_school", "major", "interest_level"],
			)
		}
		if student_ids
		else {}
	)
	school_ids = [row.get("high_school") for row in students.values() if row.get("high_school")]
	schools = (
		{
			row["name"]: row.get("school_name") or row["name"]
			for row in _get_lookup_rows(
				"CRM High School",
				filters={"name": ["in", school_ids]},
				fields=["name", "school_name"],
			)
		}
		if school_ids
		else {}
	)
	majors_ids = [row.get("major") for row in students.values() if row.get("major")]
	majors = (
		{
			row["name"]: row.get("major_name") or row["name"]
			for row in _get_lookup_rows(
				"CRM Major",
				filters={"name": ["in", majors_ids]},
				fields=["name", "major_name"],
			)
		}
		if majors_ids
		else {}
	)
	owners = (
		{
			row["name"]: row.get("full_name") or row["name"]
			for row in _get_lookup_rows(
				"CRM Staff",
				filters={"name": ["in", owner_ids]},
				fields=["name", "full_name"],
			)
		}
		if owner_ids
		else {}
	)
	return {"students": students, "schools": schools, "majors": majors, "owners": owners}


def _get_lookup_rows(doctype: str, *, filters: dict[str, Any], fields: list[str]) -> list[Any]:
	"""Load optional labels without widening the caller's read permissions.

	Some Sales profiles can read the Student/Action rows but not every linked
	master-data DocType. The NBA row is still useful in that case; its mapper
	falls back to the stored link id instead of turning a permitted queue read
	into a permission error.
	"""
	try:
		return frappe.get_list(
			doctype,
			filters=filters,
			fields=fields,
			limit_page_length=0,
		)
	except (frappe.DoesNotExistError, frappe.PermissionError):
		return []


def _map_item(row: Any, lookups: dict[str, dict[str, Any]], now) -> dict[str, Any]:
	student = lookups["students"].get(row.get("student"), {})
	student_name = student.get("student_name") or row.get("student") or "—"
	school = lookups["schools"].get(student.get("high_school")) or student.get("high_school") or "—"
	interest = student.get("interest_level") or None
	action_code = row.get("action") or ""
	action_type = row.get("action_type") or ""
	objective = row.get("objective") or ""
	status = _status_of(row, now)
	due = _due_datetime(row)
	package = _parse_json(row.get("package_seed"))
	if not isinstance(package, dict):
		package = {}
	talking_points = package.get("talking_points") if isinstance(package.get("talking_points"), list) else []
	evidence = _parse_evidence(row.get("evidence_references"))
	rationale = package.get("rationale") if isinstance(package.get("rationale"), dict) else {}
	evidence_ref_ids = rationale.get("evidence_ref_ids")
	safe_package = {key: value for key, value in package.items() if key in _PACKAGE_ALLOWED_KEYS}

	return {
		"id": row["name"],
		"studentId": row.get("student") or "",
		"studentName": student_name,
		"initials": _initials(student_name),
		"schoolId": None,
		"school": school,
		"interest": interest,
		"recommendationCode": _slug(action_code).upper() if action_code else "ACTION",
		"recommendation": objective or _action_label(action_code),
		"summary": objective,
		"dueAt": _as_iso(due) if due else None,
		"dueLabel": _due_label(status),
		"status": status,
		"priority": _priority_of(row),
		"impact": "Đưa hồ sơ sang bước tiếp theo trong hành trình tuyển sinh.",
		"currentProbability": None,
		"projectedProbability": None,
		"confidence": DEFAULT_CONFIDENCE,
		"suggestedAssigneeId": row.get("action_owner") or None,
		"suggestedAssignee": lookups["owners"].get(row.get("action_owner")) or None,
		"evidence": [str(item) for item in evidence][:8],
		"talkingPoints": [str(item) for item in talking_points][:8],
		# Additive per-type card fields (all optional; old clients ignore them).
		# A WAIT disposition writes zero CRM Action rows, so a queued row is
		# always ``ACT``; the field is emitted for the dashboard card contract.
		"actionType": action_type or None,
		"actionCode": action_code or None,
		"disposition": "ACT",
		"packageSeed": _camelize_keys(safe_package) if safe_package else None,
		"whyNow": rationale.get("why_now") or None,
		"approach": rationale.get("approach") or None,
		"expectedOutcome": rationale.get("expected_outcome") or None,
		"evidenceRefIds": (
			[str(item) for item in evidence_ref_ids] if isinstance(evidence_ref_ids, list) else []
		),
		"recentActivity": [],
		"controlLevel": _CONTROL_LEVEL_BY_TYPE.get(action_code, "review"),
		"state": _STATE_MAP.get(row.get("state"), "proposed"),
		"generatedAt": _as_iso(row.get("creation")) or "",
		"expiresAt": None,
		# CAS field for the sales decision (accept/defer/dismiss), not execution.
		"version": int(row.get("decision_revision") or 0),
	}


def _due_label(status: str) -> str:
	return {
		"overdue": "Đã quá hạn",
		"today": "Xử lý hôm nay",
		"soon": "Theo lịch",
	}.get(status, "Chưa đặt hạn")


def _action_label(action_type: str) -> str:
	return {
		"CALL": "Gọi điện",
		"EMAIL": "Gửi email",
		"MESSAGE": "Nhắn tin",
		"COUNSELING": "Tư vấn",
		"MEETING": "Gặp trực tiếp",
		"EVENT_INVITE": "Mời sự kiện",
		"CAMPUS_VISIT": "Tham quan cơ sở",
		"DOCUMENT_REQUEST": "Yêu cầu hồ sơ",
		"APPLICATION_SUPPORT": "Hỗ trợ nộp hồ sơ",
		"PARENT_CONTACT": "Liên hệ phụ huynh",
		"HANDOFF": "Chuyển tiếp",
	}.get(action_type, action_type or "Hành động")


# End-user package fields the director card may render, per
# ``docs/action-ui-contract.md`` v2 (union across the 11 types). Pointer /
# identifier fields (``recipient_ref``, ``parent_ref``, ``event_ref``,
# ``template_version``) are deliberately excluded — a generic Action reader does
# not expose recipient or routing identifiers.
_PACKAGE_ALLOWED_KEYS = frozenset(
	{
		"package_version",
		"objective",
		"opening",
		"talking_points",
		"questions",
		"objections",
		"desired_outcome",
		"next_step",
		"subject",
		"body",
		"cta",
		"channel",
		"key_points",
		"topic",
		"agenda",
		"guidance_points",
		"concerns_to_address",
		"purpose",
		"attendees_hint",
		"prep_checklist",
		"why_relevant",
		"invite_message",
		"follow_up_step",
		"visit_goal",
		"itinerary_points",
		"logistics_notes",
		"who_to_involve",
		"missing_documents",
		"deadline",
		"request_message",
		"consequence_if_missing",
		"blocking_steps",
		"support_actions",
		"reason",
		"sensitivities",
		"to_role",
		"context_summary",
		"open_items",
		"expected_response_time",
	}
)


def _camelize_keys(value: dict[str, Any]) -> dict[str, Any]:
	"""snake_case → camelCase for the top-level keys of a package seed.

	Only the keys are transformed; values (including nested lists/dicts) pass
	through untouched. The dashboard ``NbaPackageSeed`` type is the camelCase
	mirror of ``docs/action-ui-contract.md`` v2.
	"""
	out: dict[str, Any] = {}
	for key, item in value.items():
		parts = str(key).split("_")
		out[parts[0] + "".join(word[:1].upper() + word[1:] for word in parts[1:])] = item
	return out


def _parse_json(value: Any) -> Any:
	if value in (None, ""):
		return None
	if isinstance(value, dict | list):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return None


def _parse_evidence(value: Any) -> list[Any]:
	parsed = _parse_json(value)
	if isinstance(parsed, list):
		return parsed
	if isinstance(parsed, dict):
		refs = parsed.get("references") or parsed.get("evidence") or []
		return refs if isinstance(refs, list) else []
	return []


def _initials(name: str | None) -> str:
	words = [word for word in re.split(r"\s+", str(name or "").strip()) if word]
	return ("".join(word[0] for word in words[-2:]).upper()) or "—"


def _slug(value: Any) -> str:
	return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-") or "action"


def _as_iso(value: Any) -> str | None:
	if not value:
		return None
	try:
		parsed = frappe.utils.get_datetime(value)
	except (TypeError, ValueError):
		return str(value)
	if parsed.tzinfo is None:
		parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
	else:
		parsed = parsed.astimezone(LOCAL_TIMEZONE)
	return parsed.isoformat(timespec="seconds")
