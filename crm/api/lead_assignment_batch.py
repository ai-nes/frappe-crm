"""CRM Lead assignment runs.

The backend keeps the explicit batch document as an audit record, while the
operator-facing flow can simply scan every unassigned Lead and run the
province-based resolver.  The older explicit create/import APIs remain for
backward compatibility and historical records.
"""

from __future__ import annotations

import uuid
from typing import Any

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, today

from crm.api import lead_mapping
from crm.api.assignment_workspace import _actor_context
from crm.fcrm.lead_processing import (
	_set_processing_values,
	assign_lead,
	preview_lead,
)
from crm.fcrm.student_assignment import (
	ENRICHMENT_QUEUE,
	MANUAL_QUEUE,
	resolve_student_zone,
	zone_team_pool,
)
from crm.fcrm.student_ownership import change_student_ownership
from crm.fcrm.team_routing import (
	active_lead_count,
	province_for_zone,
	require_team_routing_ready,
	select_province_recipient,
)

BATCH_DOCTYPE = "CRM Lead Assignment Batch"
MAX_BATCH_SIZE = 1000
RUNNABLE_STATUSES = {"draft", "ready", "completed_with_errors"}
TERMINAL_ITEM_STATUSES = {"assigned", "skipped"}
ROUTING_REVIEW_CODES = frozenset(
	{
		"NOT_PROCESSED",
		"MISSING_PROVINCE",
		"MISSING_CAMPUS",
		"TEAM_NOT_FOUND_FOR_PROVINCE",
		"NO_ELIGIBLE_RECIPIENT",
		"TEAM_NOT_READY",
		"PROVINCE_MISMATCH",
		"TEAM_PROVINCE_MISMATCH",
		"TEAM_SCOPE_MISMATCH",
		"MISSING_INPUT_QUEUE",
		"MULTIPLE_INPUT_QUEUES",
	}
)
PERMANENT_ASSIGNMENT_ERROR_CODES = frozenset(
	{
		"INVALID_CURRENT_OWNERSHIP",
		"MISSING_PROVINCE",
		"MISSING_CAMPUS",
		"TEAM_NOT_FOUND_FOR_PROVINCE",
		"PROVINCE_MISMATCH",
		"TEAM_PROVINCE_MISMATCH",
		"TEAM_SCOPE_MISMATCH",
	}
)
BATCH_IMPORT_REQUIRED_HEADERS = frozenset(
	{"student_name", "phone", "province", "high_school", "major", "source"}
)

LEAD_ASSIGNMENT_WORKFLOW_CONNECTIONS = (
	{"source": "input", "target": "validation", "label": None},
	{"source": "validation", "target": "classification", "label": "Đủ dữ liệu"},
	{"source": "classification", "target": "matching", "label": "Đủ thông tin tuyến"},
	{
		"source": "classification",
		"target": "review",
		"label": "Cần bổ sung / duplicate",
	},
	{"source": "matching", "target": "assignment", "label": "Có quy tắc và sức chứa"},
	{"source": "matching", "target": "review", "label": "Tạm hoãn hoặc lỗi"},
	{"source": "review", "target": "assignment", "label": "Sau khi xử lý lại"},
)

LEAD_ASSIGNMENT_WORKFLOW_STEP_DEFINITIONS = (
	(
		"input",
		{
			"title": "Bước 1 · Tiếp nhận Lead",
			"description": "Lead đã được hệ thống nhận diện để phân công",
			"detail": "Hệ thống lấy các Lead đã qua bước Xử lý Lead mà chưa có người phụ trách.",
			"rules": [
				"Mỗi lần chạy có kết quả riêng để theo dõi.",
				"Thông tin gốc được giữ lại để đối chiếu.",
				"Nguồn tiếp nhận Lead nằm ngoài màn hình này.",
			],
			"tone": "blue",
		},
	),
	(
		"validation",
		{
			"title": "Bước 2 · Kiểm tra điều kiện",
			"description": "Số điện thoại · Tỉnh · Trường THPT · Ngành quan tâm",
			"detail": "Điều kiện dữ liệu được kiểm tra ở bước Xử lý Lead; đợt phân công chỉ nhận Lead đã đạt.",
			"rules": [
				"Hồ sơ thiếu trường bắt buộc được đóng ngay trong bước Xử lý Lead.",
				"Hệ thống không tự bổ sung hoặc suy đoán thông tin.",
				"Đợt chỉ chuyển sang trạng thái đã kiểm tra khi hệ thống hoàn tất bước này.",
			],
			"tone": "neutral",
		},
	),
	(
		"classification",
		{
			"title": "Bước 3 · Xác định kết quả xử lý",
			"description": "Đã xử lý · Chưa có kết quả",
			"detail": "Lead đạt đủ bốn điều kiện và được giữ nguyên kết quả để chờ các bước nghiệp vụ tiếp theo.",
			"rules": [
				"Bốn điều kiện gồm số điện thoại, tỉnh, trường THPT và ngành quan tâm.",
				"Lead không đạt điều kiện sẽ được đóng và vẫn giữ kết quả chưa có.",
				"Bước xử lý không tạo hồ sơ Student.",
				"Thông tin gốc của từng Lead vẫn được hiển thị để kiểm tra.",
			],
			"tone": "blue",
		},
	),
	(
		"matching",
		{
			"title": "Bước 4 · Tìm Team theo tỉnh",
			"description": "Tỉnh · Team phụ trách · Sale/CTV",
			"detail": "Hệ thống tìm các Team đang phụ trách tỉnh của Lead rồi chọn Sale/CTV phù hợp.",
			"rules": [
				"Tỉnh của Lead được dùng làm căn cứ tìm Team.",
				"Một tỉnh có thể có nhiều Team cùng phụ trách.",
				"Team không có người đang hoạt động sẽ không được chọn.",
			],
			"tone": "primary",
		},
	),
	(
		"review",
		{
			"title": "Ngoại lệ cần xử lý",
			"description": "Cần kiểm tra · Tạm hoãn · Lỗi xử lý",
			"detail": "Các hồ sơ chưa thể phân công được đưa vào danh sách cần kiểm tra hoặc xử lý lại.",
			"rules": [
				"Hồ sơ đã đóng cần được mở lại sau khi bổ sung dữ liệu.",
				"Hồ sơ tạm hoãn có thể được xử lý lại khi điều kiện thay đổi.",
				"Lỗi phân tuyến hiển thị nguyên nhân dễ hiểu để người vận hành xử lý.",
			],
			"tone": "warning",
		},
	),
	(
		"assignment",
		{
			"title": "Bước 5 · Ghi nhận người phụ trách",
			"description": "Team · Sale/CTV · Chưa tạo Student",
			"detail": "Kết quả phân công chỉ lưu Team, tỉnh, Sale/CTV và tải tại thời điểm chọn.",
			"rules": [
				"Lead Sale chỉ quản lý Team, không được nhận Lead.",
				"Sale và CTV Sale được chọn theo tải hiện tại và giới hạn nhận.",
				"Sau khi phân công, có thể xem lại lý do và người được chọn.",
			],
			"tone": "success",
		},
	),
)


def _require_access():
	context = _actor_context()
	capabilities = set(context["capabilities"])
	if not context.get("is_system_manager") and "student.routing.operate" not in capabilities:
		frappe.throw(
			_("Bạn không có quyền thực hiện phân công theo đợt."),
			frappe.PermissionError,
		)
	return context


def _require_read_access():
	"""Allow routing readers to inspect batch history without granting mutations."""
	context = _actor_context()
	capabilities = set(context["capabilities"])
	if not context.get("is_system_manager") and not capabilities.intersection(
		{"student.routing.read", "student.routing.operate"}
	):
		frappe.throw(
			_("Bạn không có quyền xem lịch sử phân công theo đợt."),
			frappe.PermissionError,
		)
	return context


def _parse_list(value: Any, label: str) -> list[str]:
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			value = [part.strip() for part in value.split(",") if part.strip()]
	if not isinstance(value, (list, tuple, set)):
		frappe.throw(_("{0} phải là một danh sách.").format(label), frappe.ValidationError)
	values = []
	for item in value:
		item = str(item or "").strip()
		if item and item not in values:
			values.append(item)
	if not values:
		frappe.throw(_("{0} không được rỗng.").format(label), frappe.ValidationError)
	if len(values) > MAX_BATCH_SIZE:
		frappe.throw(
			_("Một đợt tối đa {0} Lead.").format(MAX_BATCH_SIZE),
			frappe.ValidationError,
		)
	return values


def _lead_permission(lead) -> None:
	if not frappe.has_permission("CRM Lead", ptype="read", doc=lead, user=frappe.session.user):
		frappe.throw(_("Lead nằm ngoài phạm vi của bạn."), frappe.PermissionError)


def _lead(name: str):
	if not frappe.db.exists("CRM Lead", name):
		frappe.throw(_("Không tìm thấy Lead: {0}.").format(name), frappe.ValidationError)
	doc = frappe.get_doc("CRM Lead", name)
	_lead_permission(doc)
	return doc


def _close_invalid_assignment_lead(lead_name: str, reason: str) -> None:
	"""Close a Lead that cannot ever be routed with its current data."""
	_set_processing_values(
		lead_name,
		{
			"processing_status": "CLOSED",
			"resolution": "PENDING",
			"resolution_reason": reason[:500],
		},
	)


def _retryable_item(item) -> bool:
	"""True when a failed item may be reset and run again.

	A permanent error also closed its Lead, so the item stays untouched until an
	operator reopens that Lead — their explicit statement that the routing data
	behind the failure has been corrected.
	"""
	if item.status not in {"deferred", "manual_review", "failed"}:
		return False
	if item.error_code not in PERMANENT_ASSIGNMENT_ERROR_CODES:
		return True
	status = frappe.db.get_value("CRM Lead", item.lead, "processing_status")
	return str(status or "").strip().upper() != "CLOSED"


def _batch_item_lead(item):
	"""Load one batch item's Lead, tolerating ownership this batch itself committed.

	The operator's row scope is enforced when the Lead enters the batch. Once the
	run commits ownership to a Sale on another Team the Lead leaves that scope, so
	re-reading it with the operator scope would fail the conversion step and every
	later retry of a Lead the batch already assigned.
	"""
	name = item.lead
	if not frappe.db.exists("CRM Lead", name):
		frappe.throw(_("Không tìm thấy Lead: {0}.").format(name), frappe.ValidationError)
	doc = frappe.get_doc("CRM Lead", name)
	assigned_by_batch = bool(item.owner_staff) and item.owner_staff in {
		doc.get("owner_staff"),
		doc.get("assigned_to"),
	}
	if not assigned_by_batch:
		_lead_permission(doc)
	return doc


def _pool(pool_name: str | None, branch: str | None, actor_context: dict[str, Any] | None = None):
	if not pool_name:
		return None
	pool = frappe.db.get_value(
		"CRM Student Pool",
		pool_name,
		["name", "team", "campus", "is_active"],
		as_dict=True,
	)
	if not pool or not pool.is_active:
		frappe.throw(_("Hàng chờ đầu vào không tồn tại hoặc đã tắt."), frappe.ValidationError)
	if branch and pool.campus != branch:
		frappe.throw(_("Hàng chờ và cơ sở của Lead không khớp."), frappe.ValidationError)
	if actor_context and not actor_context.get("is_system_manager"):
		allowed_teams = set(actor_context.get("teams") or [])
		allowed_campuses = set(actor_context.get("campuses") or [])
		if pool.team not in allowed_teams or pool.campus not in allowed_campuses:
			frappe.throw(_("Hàng chờ nằm ngoài phạm vi Team/cơ sở của bạn."), frappe.PermissionError)
	return pool


def _reset_item(item, *, status: str = "pending", reason: str | None = None):
	for fieldname in (
		"error_code",
		"routing_tier",
		"queue",
		"zone",
		"team",
		"owner_staff",
		"active_load",
		"capacity_limit",
		"remaining_capacity",
		"policy_version",
		"routing_request",
		"completed_at",
	):
		item.set(fieldname, None)
	for fieldname in ("active_load", "capacity_limit", "remaining_capacity"):
		item.set(fieldname, 0)
	item.status = status
	item.reason = reason


def _queue_for_zone(lead, routing_context: dict[str, Any]) -> str | None:
	tier = routing_context.get("tier")
	if tier == 3:
		province = str(lead.get("province") or "").strip()
		return f"PROVINCE:{province}" if province else MANUAL_QUEUE
	if tier == 4:
		return ENRICHMENT_QUEUE
	return None


def _expected_team_province(lead, routing_context: dict[str, Any]) -> str | None:
	"""Use canonical Province links, never free-text geography labels."""
	zone = routing_context.get("zone")
	return province_for_zone(zone) or lead.get("province")


def _raise_batch_error(code: str, message: str):
	exception = frappe.ValidationError(message)
	exception.code = code
	exception.error_code = code
	raise exception


def _team_scope(team_id: str | None, actor_context: dict[str, Any]) -> dict[str, Any] | None:
	if not team_id:
		return None
	team = frappe.db.get_value(
		"CRM Team",
		team_id,
		["name", "team_name", "group", "campus", "is_active", "team_type"],
		as_dict=True,
	)
	if not team or not team.is_active:
		_raise_batch_error("TEAM_NOT_FOUND", "Team nhận batch không tồn tại hoặc đã tắt.")
	if not actor_context.get("is_system_manager") and team.name not in set(actor_context.get("teams") or []):
		frappe.throw(_("Team nằm ngoài phạm vi của bạn."), frappe.PermissionError)
	group = (
		frappe.db.get_value(
			"CRM Team Group",
			team.group,
			["name", "province", "is_active"],
			as_dict=True,
		)
		if team.group
		else None
	)
	if not group or not group.is_active or not group.province:
		_raise_batch_error("TEAM_NOT_READY", "Team chưa thuộc Group có tỉnh đang hoạt động.")
	return {**dict(team), "groupProvince": group.province}


def _canonical_province(value: str | None) -> str | None:
	value = str(value or "").strip()
	if not value:
		return None
	if frappe.db.exists("CRM Province", value):
		return value
	return lead_mapping._resolve_province(value)


def _validate_batch_scope(batch, lead, actor_context: dict[str, Any]) -> None:
	lead_province = str(lead.get("province") or "").strip()
	if batch.province and lead_province != batch.province:
		_raise_batch_error(
			"PROVINCE_MISMATCH",
			"Tỉnh của Lead không khớp với tỉnh đã xác định cho batch.",
		)
	if batch.target_team:
		team = _team_scope(batch.target_team, actor_context)
		if team and lead_province != team["groupProvince"]:
			_raise_batch_error(
				"TEAM_PROVINCE_MISMATCH",
				"Tỉnh của Lead không khớp với Group của Team nhận batch.",
			)


def _sync_batch_scope(batch, actor_context: dict[str, Any]) -> None:
	"""Persist the province inferred from the batch without changing Leads."""
	if batch.target_team:
		team = _team_scope(batch.target_team, actor_context)
		if batch.province and batch.province != team["groupProvince"]:
			_raise_batch_error(
				"TEAM_PROVINCE_MISMATCH",
				"Team nhận batch không thuộc tỉnh đã chọn.",
			)
		batch.province = team["groupProvince"]
		return
	if batch.province:
		return
	provinces = {
		str(frappe.db.get_value("CRM Lead", item.lead, "province") or "").strip()
		for item in batch.items
		if item.lead
	}
	provinces.discard("")
	if len(provinces) == 1:
		batch.province = next(iter(provinces))


def _validate_batch_pool(pool, lead, routing_context):
	if not pool:
		return None
	require_team_routing_ready(
		pool.team,
		campus=pool.campus,
		expected_province=_expected_team_province(lead, routing_context),
	)
	return pool


def _resolve_batch_pool(batch, lead, actor_context: dict[str, Any]):
	"""Resolve the internal intake Pool without exposing it to operators."""
	context = resolve_student_zone(lead)
	if batch.target_team:
		team = _team_scope(batch.target_team, actor_context)
		mapped_team = context.get("school_owner_team")
		if context.get("zone") and not mapped_team:
			mapping = zone_team_pool(context["zone"], lead.get("branch"))
			mapped_team = mapping.get("team") if mapping else None
		if mapped_team and mapped_team != team["name"]:
			_raise_batch_error(
				"TEAM_SCOPE_MISMATCH",
				"Team nhận batch không phụ trách Zone/Trường của Lead.",
			)
		pool_rows = frappe.get_all(
			"CRM Student Pool",
			filters={"team": team["name"], "campus": lead.get("branch"), "is_active": 1},
			fields=["name", "team", "campus", "is_active"],
			limit_page_length=2,
		)
		if len(pool_rows) > 1:
			_raise_batch_error("MULTIPLE_INPUT_QUEUES", "Team nhận batch có nhiều hàng chờ đang hoạt động.")
		if not pool_rows:
			_raise_batch_error("MISSING_INPUT_QUEUE", "Team nhận batch chưa có hàng chờ đang hoạt động.")
		pool = _pool(pool_rows[0].name, lead.get("branch"), actor_context)
		return _validate_batch_pool(pool, lead, context)

	pool_name = lead.get("owning_pool") or batch.get("pool")
	if pool_name:
		pool = _pool(pool_name, lead.get("branch"), actor_context)
		if pool:
			return _validate_batch_pool(pool, lead, context)

	branch = lead.get("branch")
	# A Lead with a mapped school/Zone already contains enough information to
	# find the correct Team. Resolve this before looking at campus-wide pools;
	# otherwise multiple Teams in one Campus make the old Pool selector win.
	if context.get("zone"):
		mapping = zone_team_pool(context["zone"], branch)
		if mapping and mapping.get("pool"):
			return _validate_batch_pool(_pool(mapping["pool"], branch, actor_context), lead, context)

	filters = {"is_active": 1, "campus": branch}
	if not actor_context.get("is_system_manager"):
		filters["team"] = ["in", actor_context.get("teams") or ["__no_team__"]]
	candidates = frappe.get_all(
		"CRM Student Pool",
		filters=filters,
		fields=["name", "team", "campus", "is_active"],
		limit_page_length=3,
	)
	if len(candidates) == 1:
		return _validate_batch_pool(_pool(candidates[0].name, branch, actor_context), lead, context)
	if len(candidates) > 1:
		raise frappe.ValidationError("MULTIPLE_INPUT_QUEUES")

	# System Managers may not have an actor Team. If no school/Zone mapping is
	# available, retain the safe legacy fallback only when one campus Pool exists.
	# Multiple Teams remain a Province/manual-review case; never guess a Team.
	if actor_context.get("is_system_manager"):
		campus_pools = frappe.get_all(
			"CRM Student Pool",
			filters={"is_active": 1, "campus": branch},
			fields=["name", "team", "campus", "is_active"],
			limit_page_length=3,
		)
		if len(campus_pools) == 1:
			return _validate_batch_pool(_pool(campus_pools[0].name, branch, actor_context), lead, context)
		if len(campus_pools) > 1:
			raise frappe.ValidationError("MULTIPLE_INPUT_QUEUES")
	raise frappe.ValidationError("MISSING_INPUT_QUEUE")


def _preview_item(
	batch,
	item,
	actor_context: dict[str, Any],
	*,
	load_overrides: dict[str, int] | None = None,
) -> None:
	lead = _batch_item_lead(item)
	_validate_batch_scope(batch, lead, actor_context)
	if lead.get("converted_student") or lead.get("conversion_status") == "Converted":
		_reset_item(item, status="skipped", reason="ALREADY_CONVERTED")
		item.ownership_revision = int(lead.get("ownership_revision") or 0)
		return
	if lead.get("owner_staff") or lead.get("assigned_to"):
		_reset_item(item, status="skipped", reason="ALREADY_ASSIGNED")
		item.ownership_revision = int(lead.get("ownership_revision") or 0)
		return
	processing_status = str(lead.get("processing_status") or "NEW").upper()
	if processing_status in {"NEW", "PROCESSING"}:
		# preview_lead predicts what processing *would* decide for a NEW Lead, but
		# the run no longer processes on the operator's behalf, so previewing it as
		# assignable would promise an outcome the run cannot deliver.
		_reset_item(item, status="manual_review", reason="NOT_PROCESSED")
		item.error_code = "NOT_PROCESSED"
		return
	processing = preview_lead(lead.name)
	item.reason = processing.get("reason") or "Đã kiểm tra đủ 4 điều kiện."
	item.error_code = processing.get("error_code")
	if processing.get("status") == "CLOSED":
		_reset_item(
			item, status="manual_review", reason=processing.get("reason") or processing.get("resolution")
		)
		item.error_code = processing.get("error_code") or processing.get("resolution")
		return
	if processing.get("status") != "PROCESSED":
		_reset_item(item, status="manual_review", reason="INVALID_PROCESSING_STATUS")
		item.error_code = "INVALID_PROCESSING_STATUS"
		return
	province = _canonical_province(lead.get("province"))
	if not province:
		_close_invalid_assignment_lead(lead.name, "Lead bị đóng: thiếu tỉnh để xác định Team quản lý.")
		_reset_item(item, status="failed", reason="MISSING_PROVINCE")
		item.error_code = "MISSING_PROVINCE"
		return
	recipient = _resolve_batch_recipient(
		batch,
		lead,
		actor_context,
		load_overrides=load_overrides,
	)
	item.status = "pending"
	item.reason = recipient["reason"]
	item.routing_tier = "province"
	item.queue = f"PROVINCE:{province}"
	item.zone = None
	item.team = recipient["team"]
	item.owner_staff = recipient["ownerStaff"]
	item.active_load = int(recipient["capacity"].get("active") or 0)
	item.capacity_limit = int(recipient["capacity"].get("limit") or 0)
	item.remaining_capacity = int(recipient["capacity"].get("remaining") or 0)
	item.policy_version = recipient["policyVersion"]
	item.ownership_revision = int(lead.get("ownership_revision") or 0)
	item.error_code = None


def _resolve_batch_recipient(batch, lead, actor_context: dict[str, Any], *, load_overrides=None):
	"""Resolve a Team and Sale/CTV from the Lead's canonical Province."""
	province = _canonical_province(lead.get("province"))
	if not province:
		_raise_batch_error("MISSING_PROVINCE", "Lead chưa có tỉnh để phân công.")
	_validate_batch_scope(batch, lead, actor_context)
	return select_province_recipient(
		province,
		campus=lead.get("branch"),
		team_id=batch.target_team or None,
		load_overrides=load_overrides,
	)


def _preview_batch_items(batch, actor_context: dict[str, Any]) -> None:
	"""Evaluate every item before execution, keeping exceptions out of the run path."""
	_sync_batch_scope(batch, actor_context)
	load_overrides: dict[str, int] = {}
	for item in batch.items:
		if item.status in TERMINAL_ITEM_STATUSES:
			continue
		try:
			_preview_item(batch, item, actor_context, load_overrides=load_overrides)
			if item.status == "pending" and item.owner_staff:
				load_overrides[item.owner_staff] = load_overrides.get(item.owner_staff, 0) + 1
		except Exception as exc:
			code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
			if not code and str(exc).strip() in {
				"MISSING_PROVINCE",
				"MISSING_CAMPUS",
				"TEAM_NOT_FOUND_FOR_PROVINCE",
				"NO_ELIGIBLE_RECIPIENT",
				"TEAM_NOT_READY",
				"PROVINCE_MISMATCH",
			}:
				code = str(exc).strip()
			code = code or "PREVIEW_FAILED"
			if code in PERMANENT_ASSIGNMENT_ERROR_CODES:
				_close_invalid_assignment_lead(item.lead, f"Lead bị đóng: {exc}")
			_reset_item(
				item,
				status="failed" if code in PERMANENT_ASSIGNMENT_ERROR_CODES else "manual_review",
				reason=code,
			)
			item.error_code = code
	batch.status = "ready"


def _count_items(batch) -> None:
	counts = {"assigned": 0, "deferred": 0, "manual_review": 0, "failed": 0}
	for item in batch.items:
		if item.status in counts:
			counts[item.status] += 1
	batch.total_count = len(batch.items)
	batch.assigned_count = counts["assigned"]
	batch.deferred_count = counts["deferred"]
	batch.manual_review_count = counts["manual_review"]
	batch.failed_count = counts["failed"]


def _persist_item(item) -> None:
	"""Persist the audit row independently after ownership commits.

	``assign_lead`` commits the Lead ownership transaction by design. Saving the
	parent batch's in-memory child row afterwards was not reliable across that
	transaction boundary, leaving successful items as ``pending`` in history.
	"""
	fields = (
		"status",
		"reason",
		"error_code",
		"routing_tier",
		"queue",
		"zone",
		"team",
		"owner_staff",
		"active_load",
		"capacity_limit",
		"remaining_capacity",
		"policy_version",
		"ownership_revision",
		"routing_request",
		"execution_id",
		"completed_at",
	)
	frappe.db.set_value(
		"CRM Lead Assignment Batch Item",
		item.name,
		{
			fieldname: (
				int(item.get(fieldname) or 0)
				if fieldname in {"active_load", "capacity_limit", "remaining_capacity", "ownership_revision"}
				else item.get(fieldname)
			)
			for fieldname in fields
		},
		update_modified=True,
	)


def _serialize_item(item) -> dict[str, Any]:
	lead_state = (
		frappe.db.get_value(
			"CRM Lead",
			item.lead,
			["processing_status", "owner_staff", "assigned_to"],
			as_dict=True,
		)
		or {}
	)
	processing_status = lead_state.get("processing_status")
	lead_owner = lead_state.get("owner_staff") or lead_state.get("assigned_to")
	item_status = _effective_history_item_status(item.status, processing_status)
	lead = (
		frappe.db.get_value(
			"CRM Lead",
			item.lead,
			[
				"student_name",
				"phone",
				"id_number",
				"email",
				"province",
				"high_school",
				"major",
				"source",
				"branch",
			],
			as_dict=True,
		)
		or {}
	)
	return {
		"id": item.name,
		"lead": item.lead,
		"leadId": item.lead,
		"studentName": lead.get("student_name") or item.lead,
		"phone": lead.get("phone"),
		"idNumber": lead.get("id_number"),
		"email": lead.get("email"),
		"province": lead.get("province"),
		"highSchool": lead.get("high_school"),
		"major": lead.get("major"),
		"source": lead.get("source"),
		"branch": lead.get("branch"),
		"status": item_status,
		"reason": item.reason,
		"errorCode": item.error_code,
		"routingTier": item.routing_tier,
		"queue": item.queue,
		"zone": item.zone,
		"team": item.team,
		"ownerStaff": lead_owner or item.owner_staff,
		"activeLoad": item.active_load,
		"capacityLimit": item.capacity_limit or None,
		"remainingCapacity": item.remaining_capacity if item.capacity_limit else None,
		"policyVersion": item.policy_version,
		"ownershipRevision": item.ownership_revision,
		"routingRequest": item.routing_request,
		"executionId": item.execution_id,
		"completedAt": str(item.completed_at) if item.completed_at else None,
		"processingStatus": processing_status,
		"resolution": frappe.db.get_value("CRM Lead", item.lead, "resolution"),
		"matchedStudent": frappe.db.get_value("CRM Lead", item.lead, "matched_student"),
		"convertedStudent": frappe.db.get_value("CRM Lead", item.lead, "converted_student"),
	}


def _effective_history_item_status(item_status: str, processing_status: str | None) -> str:
	"""Project a batch item using the current Lead state.

	The batch row is an audit snapshot, while ownership and processing status on
	the Lead are live state.  A previous run can therefore leave a pending item
	behind after ownership has already been committed.
	"""
	current_status = str(processing_status or "").strip().upper()
	if current_status == "ASSIGNED":
		return "assigned"
	if current_status == "CLOSED":
		return "manual_review"
	return item_status


def _live_review_missing_fields(lead) -> list[str]:
	fields = (
		("phone", "Số điện thoại"),
		("province", "Tỉnh"),
		("high_school", "Trường THPT"),
		("major", "Ngành quan tâm"),
	)
	return [label for fieldname, label in fields if not str(lead.get(fieldname) or "").strip()]


def _serialize_live_review_item(lead) -> dict[str, Any]:
	"""Project a currently closed Lead into the operator's review queue."""
	resolution = lead.get("resolution") or "PENDING"
	reason = lead.get("resolution_reason") or "Hồ sơ đang đóng và cần kiểm tra lại."
	return {
		"id": lead.name,
		"lead": lead.name,
		"leadId": lead.name,
		"studentName": lead.get("student_name") or lead.name,
		"phone": lead.get("phone"),
		"idNumber": lead.get("id_number"),
		"email": lead.get("email"),
		"province": lead.get("province"),
		"highSchool": lead.get("high_school"),
		"major": lead.get("major"),
		"source": lead.get("source"),
		"branch": lead.get("branch"),
		"status": "manual_review",
		"reason": reason,
		"errorCode": "DUPLICATE" if resolution == "DUPLICATE" else "LEAD_CLOSED",
		"missingFields": _live_review_missing_fields(lead),
		"routingTier": None,
		"queue": None,
		"zone": None,
		"team": None,
		"ownerStaff": lead.get("owner_staff") or lead.get("assigned_to"),
		"activeLoad": None,
		"capacityLimit": None,
		"remainingCapacity": None,
		"policyVersion": None,
		"ownershipRevision": int(lead.get("ownership_revision") or 0),
		"routingRequest": None,
		"executionId": None,
		"completedAt": str(lead.modified) if lead.get("modified") else None,
		"processingStatus": "CLOSED",
		"resolution": resolution,
		"matchedStudent": lead.get("matched_student"),
		"convertedStudent": lead.get("converted_student"),
		"batchId": "",
		"batchCreatedAt": str(lead.get("modified") or lead.get("creation") or ""),
		"batchStatus": "completed_with_errors",
	}


def _live_closed_leads(lead_ids: set[str] | None = None) -> list[dict[str, Any]]:
	filters: dict[str, Any] = {"processing_status": "CLOSED"}
	if lead_ids:
		filters["name"] = ["in", sorted(lead_ids)]
	return frappe.get_list(
		"CRM Lead",
		filters=filters,
		fields=[
			"name",
			"student_name",
			"phone",
			"id_number",
			"email",
			"province",
			"high_school",
			"major",
			"source",
			"branch",
			"owner_staff",
			"assigned_to",
			"ownership_revision",
			"matched_student",
			"converted_student",
			"processing_status",
			"resolution",
			"resolution_reason",
			"creation",
			"modified",
		],
		order_by="modified desc, name desc",
		limit_page_length=0,
	)


def _batch_summary(batch) -> dict[str, int]:
	_count_items(batch)
	return {
		"total": batch.total_count,
		"valid": max(0, batch.total_count - batch.manual_review_count),
		"invalid": batch.manual_review_count,
		"pending": sum(item.status == "pending" for item in batch.items),
		"assigned": batch.assigned_count,
		"deferred": batch.deferred_count,
		"manualReview": batch.manual_review_count,
		"failed": batch.failed_count,
		"skipped": sum(item.status == "skipped" for item in batch.items),
	}


def _serialize_batch_header(batch) -> dict[str, Any]:
	return {
		"id": batch.name,
		"batchName": batch.batch_name,
		"description": batch.description,
		"status": batch.status,
		"itemCount": batch.total_count,
		"summary": _batch_summary(batch),
		"createdAt": str(batch.get("creation")) if batch.get("creation") else None,
		"updatedAt": str(batch.get("modified")) if batch.get("modified") else None,
		"previewedAt": str(batch.get("previewed_at")) if batch.get("previewed_at") else None,
		"completedAt": str(batch.get("completed_at")) if batch.get("completed_at") else None,
	}


def _workflow_metrics(summary: dict[str, int], step_id: str) -> dict[str, int]:
	attention = summary["deferred"] + summary["manualReview"]
	if step_id == "input":
		return {
			"processedCount": summary["total"],
			"successCount": summary["total"],
			"warningCount": summary["invalid"],
			"errorCount": 0,
		}
	if step_id == "validation":
		return {
			"processedCount": summary["total"],
			"successCount": summary["valid"],
			"warningCount": summary["invalid"],
			"errorCount": 0,
		}
	if step_id == "classification":
		return {
			"processedCount": summary["valid"],
			"successCount": max(0, summary["valid"] - summary["failed"]),
			"warningCount": attention,
			"errorCount": summary["failed"],
		}
	if step_id == "matching":
		return {
			"processedCount": summary["valid"],
			"successCount": summary["assigned"],
			"warningCount": attention,
			"errorCount": summary["failed"],
		}
	if step_id == "review":
		return {
			"processedCount": attention + summary["failed"],
			"successCount": 0,
			"warningCount": attention,
			"errorCount": summary["failed"],
		}
	return {
		"processedCount": summary["total"],
		"successCount": summary["assigned"],
		"warningCount": attention,
		"errorCount": summary["failed"],
	}


def _empty_workflow_summary() -> dict[str, int]:
	return {
		"total": 0,
		"valid": 0,
		"invalid": 0,
		"pending": 0,
		"assigned": 0,
		"deferred": 0,
		"manualReview": 0,
		"failed": 0,
		"skipped": 0,
	}


def _processing_workflow_summary() -> dict[str, int]:
	"""Project current Leads and assignment history into one live summary.

	Assigned Leads can leave the operator's normal Lead scope after ownership is
	committed.  The assignment batch remains the audit boundary for those Leads,
	so the workflow must reconcile the latest batch item with the live Lead state
	before counting them.
	"""
	latest_by_lead: dict[str, str] = {}
	batch_page = 1
	while True:
		batch_response = list_lead_assignment_batches(limit=100, page=batch_page)
		for batch_row in batch_response.get("items", []):
			batch = frappe.get_doc(BATCH_DOCTYPE, batch_row["name"])
			for item in batch.items:
				lead_id = str(item.lead or "").strip()
				if not lead_id or lead_id in latest_by_lead:
					continue
				lead_state = (
					frappe.db.get_value(
						"CRM Lead",
						lead_id,
						["processing_status", "owner_staff", "assigned_to"],
						as_dict=True,
					)
					or {}
				)
				latest_by_lead[lead_id] = _effective_history_item_status(
					item.status,
					lead_state.get("processing_status"),
				)
		if not batch_response.get("pagination", {}).get("has_next_page"):
			break
		batch_page += 1

	rows = frappe.get_list(
		"CRM Lead",
		filters={"processing_status": ["in", ["PROCESSED", "ASSIGNED", "CLOSED"]]},
		fields=["name", "processing_status", "owner_staff", "assigned_to"],
		limit_page_length=0,
	)
	summary = _empty_workflow_summary()
	for row in rows:
		lead_id = str(row.get("name") or "").strip()
		if lead_id in latest_by_lead:
			continue
		status = str(row.get("processing_status") or "").strip().upper()
		has_owner = bool(row.get("owner_staff") or row.get("assigned_to"))
		latest_by_lead[lead_id] = (
			"manual_review"
			if status == "CLOSED"
			else "assigned"
			if status == "ASSIGNED" or has_owner
			else "pending"
		)

	for item_status in latest_by_lead.values():
		summary["total"] += 1
		if item_status == "manual_review":
			summary["invalid"] += 1
			summary["manualReview"] += 1
			continue
		summary["valid"] += 1
		if item_status in summary:
			summary[item_status] += 1
	return summary


def _workflow_status(batch_status: str | None, step_id: str, summary: dict[str, int]) -> str:
	attention_count = summary["deferred"] + summary["manualReview"] + summary["failed"]
	has_lead = summary["total"] > 0
	if not batch_status:
		if not has_lead:
			return "idle"
		if step_id == "input":
			return "success"
		if step_id in {"validation", "classification"}:
			return "success" if summary["valid"] else "warning"
		if step_id == "matching":
			if summary["pending"]:
				return "running"
			return "success" if summary["assigned"] else "idle"
		if step_id == "review":
			return "warning" if attention_count else "idle"
		if step_id == "assignment":
			return "success" if summary["assigned"] else "idle"
		return "idle"
	if batch_status == "draft":
		if step_id == "input":
			return "success" if has_lead else "idle"
		if step_id == "validation" and has_lead:
			return "running"
		return "idle"
	if batch_status == "ready":
		if step_id in {"input", "validation", "classification", "matching"}:
			return "success"
		return "warning" if step_id == "review" and attention_count else "idle"
	if batch_status == "running":
		if step_id in {"input", "validation", "classification", "matching"}:
			return "success"
		if step_id == "assignment":
			return "running"
		return "warning" if step_id == "review" and attention_count else "idle"
	if batch_status == "completed":
		return "success"
	if batch_status == "completed_with_errors":
		if step_id == "review":
			return "warning"
		if step_id == "assignment" and summary["assigned"] == 0:
			return "error"
		return "success"
	if batch_status == "cancelled":
		if step_id == "assignment":
			return "error"
		return "success" if step_id == "input" else "idle"
	return "idle"


def _serialize_assignment_workflow(batch=None, summary: dict[str, int] | None = None) -> dict[str, Any]:
	if batch:
		workflow_summary = _batch_summary(batch)
	else:
		workflow_summary = summary or _empty_workflow_summary()
	has_data = workflow_summary["total"] > 0
	return {
		"hasRun": bool(batch),
		"hasData": has_data,
		"summary": workflow_summary,
		"pendingCount": workflow_summary["pending"],
		"batch": _serialize_batch_header(batch) if batch else None,
		"connections": list(LEAD_ASSIGNMENT_WORKFLOW_CONNECTIONS),
		"steps": [
			{
				"id": step_id,
				**definition,
				"status": _workflow_status(batch.status if batch else None, step_id, workflow_summary),
				"metrics": _workflow_metrics(workflow_summary, step_id),
			}
			for step_id, definition in LEAD_ASSIGNMENT_WORKFLOW_STEP_DEFINITIONS
		],
	}


def _serialize_batch(batch) -> dict[str, Any]:
	_count_items(batch)
	return {
		"name": batch.name,
		"batchName": batch.batch_name,
		"status": batch.status,
		"province": batch.province,
		"targetTeam": batch.target_team,
		"source": batch.source,
		"pool": batch.pool,
		"description": batch.description,
		"createdBy": batch.created_by,
		"executionId": batch.execution_id,
		"startedAt": str(batch.started_at) if batch.started_at else None,
		"completedAt": str(batch.completed_at) if batch.completed_at else None,
		"summary": _batch_summary(batch),
		"items": [_serialize_item(item) for item in batch.items],
	}


def _save_batch(batch):
	_count_items(batch)
	batch.save(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def create_lead_assignment_batch(
	batch_name: str,
	lead_ids: list[str] | str,
	pool: str | None = None,
	province: str | None = None,
	target_team: str | None = None,
	source: str | None = None,
	description: str | None = None,
):
	"""Create a draft batch without changing any Lead ownership."""
	actor_context = _require_access()
	batch_name = str(batch_name or "").strip()
	if not batch_name:
		frappe.throw(_("Tên đợt là bắt buộc."), frappe.ValidationError)
	if frappe.db.exists(BATCH_DOCTYPE, {"batch_name": batch_name}):
		frappe.throw(_("Tên đợt đã tồn tại."), frappe.DuplicateEntryError)
	lead_names = _parse_list(lead_ids, "lead_ids")
	if pool:
		_pool(pool, None, actor_context)
	canonical_province = _canonical_province(province) if province else None
	team_scope = _team_scope(target_team, actor_context) if target_team else None
	if team_scope:
		if canonical_province and canonical_province != team_scope["groupProvince"]:
			_raise_batch_error("TEAM_PROVINCE_MISMATCH", "Team nhận batch không thuộc tỉnh đã chọn.")
		canonical_province = team_scope["groupProvince"]
	batch = frappe.get_doc(
		{
			"doctype": BATCH_DOCTYPE,
			"batch_name": batch_name,
			"status": "draft",
			"province": canonical_province,
			"target_team": team_scope["name"] if team_scope else target_team,
			"pool": pool,
			"source": (source or "").strip()[:140],
			"description": (description or "").strip(),
			"created_by": frappe.session.user,
		}
	)
	for lead_name in lead_names:
		lead = _lead(lead_name)
		batch.append(
			"items",
			{
				"lead": lead.name,
				"status": "pending",
				"ownership_revision": int(lead.get("ownership_revision") or 0),
			},
		)
	if batch.province or batch.target_team:
		for item in batch.items:
			_validate_batch_scope(batch, _lead(item.lead), actor_context)
	_save_batch(batch)
	frappe.db.commit()
	return _serialize_batch(batch)


def _parse_batch_import_rows(rows: list[dict[str, Any]] | str | None, csv_content: str | None):
	if csv_content is not None:
		return lead_mapping._parse_csv_rows(
			csv_content,
			required_headers=BATCH_IMPORT_REQUIRED_HEADERS,
		)
	if isinstance(rows, str):
		try:
			rows = frappe.parse_json(rows)
		except (TypeError, ValueError):
			frappe.throw(_("rows phải là JSON array hợp lệ."), frappe.ValidationError)
	if not isinstance(rows, list) or not rows:
		frappe.throw(_("Cần truyền rows hoặc csv_content."), frappe.ValidationError)
	if len(rows) > MAX_BATCH_SIZE:
		frappe.throw(_("Một đợt tối đa {0} Lead.").format(MAX_BATCH_SIZE), frappe.ValidationError)
	return [lead_mapping._parse_public_payload(row) for row in rows]


def _default_campus(row: dict[str, Any], actor_context: dict[str, Any]) -> str:
	requested_branch = str(row.get("branch") or "").strip()
	allowed_campuses = set(actor_context.get("campuses") or [])
	if requested_branch:
		resolved_branch = lead_mapping._normalize_public_lead_payload(
			{**row, "branch": requested_branch}, require_campaign=False
		).get("branch")
		if (
			resolved_branch
			and not actor_context.get("is_system_manager")
			and resolved_branch not in allowed_campuses
		):
			frappe.throw(_("Cơ sở của Lead nằm ngoài phạm vi của bạn."), frappe.PermissionError)
		return resolved_branch
	if actor_context.get("is_system_manager"):
		default_campus = frappe.db.get_value("CRM Campus", {"is_default": 1}, "name")
		if default_campus:
			return default_campus
		campuses = frappe.get_all(
			"CRM Campus",
			filters={"approval_state": ["!=", "Retired"]},
			pluck="name",
			limit_page_length=2,
		)
		if len(campuses) == 1:
			return campuses[0]
	if len(allowed_campuses) == 1:
		return next(iter(allowed_campuses))
	frappe.throw(
		_("Không xác định được cơ sở. Hãy thêm cột Cơ sở khi tài khoản phụ trách nhiều cơ sở."),
		frappe.ValidationError,
	)


def _create_batch_import_lead(row: dict[str, Any], actor_context: dict[str, Any]):
	for fieldname, label in (
		("student_name", "Họ và tên"),
		("phone", "Di động"),
		("province", "Tỉnh/Thành phố"),
		("high_school", "Trường THPT"),
		("major", "Ngành quan tâm"),
		("source", "Nguồn"),
	):
		if not str(row.get(fieldname) or "").strip():
			frappe.throw(_("{0} là bắt buộc.").format(label), frappe.ValidationError)
	# Batch import is an authenticated internal intake flow. Campaign attribution
	# is optional here; public lead intake keeps its stricter campaign contract.
	values = lead_mapping._normalize_public_lead_payload(
		{**row, "branch": _default_campus(row, actor_context)},
		require_campaign=False,
	)
	doc = frappe.get_doc({"doctype": "CRM Lead", **values})
	doc.check_permission("create")
	doc.insert()
	return doc


@frappe.whitelist(methods=["POST"])
def import_leads_to_assignment_batch(
	batch_name: str,
	pool: str | None = None,
	province: str | None = None,
	target_team: str | None = None,
	rows: list[dict[str, Any]] | str | None = None,
	csv_content: str | None = None,
	filename: str | None = None,
	description: str | None = None,
):
	"""Import Leads into a draft batch without selecting a Sale."""
	actor_context = _require_access()
	batch_name = str(batch_name or "").strip()
	if not batch_name:
		frappe.throw(_("Tên đợt là bắt buộc."), frappe.ValidationError)
	if frappe.db.exists(BATCH_DOCTYPE, {"batch_name": batch_name}):
		frappe.throw(_("Tên đợt đã tồn tại."), frappe.DuplicateEntryError)
	input_pool = _pool(str(pool or "").strip(), None, actor_context) if pool else None
	canonical_province = _canonical_province(province) if province else None
	team_scope = _team_scope(target_team, actor_context) if target_team else None
	if team_scope:
		if canonical_province and canonical_province != team_scope["groupProvince"]:
			_raise_batch_error("TEAM_PROVINCE_MISMATCH", "Team nhận batch không thuộc tỉnh đã chọn.")
		canonical_province = team_scope["groupProvince"]
	parsed_rows = _parse_batch_import_rows(rows, csv_content)
	batch = frappe.get_doc(
		{
			"doctype": BATCH_DOCTYPE,
			"batch_name": batch_name,
			"status": "draft",
			"province": canonical_province,
			"target_team": team_scope["name"] if team_scope else target_team,
			"pool": input_pool.name if input_pool else None,
			"source": (filename or "dashboard-crm").strip()[:140],
			"description": (description or "Nhập Lead vào đợt phân công.").strip(),
			"created_by": frappe.session.user,
		}
	)
	batch.insert(ignore_permissions=True)
	created = []
	errors = []
	for index, row in enumerate(parsed_rows, start=2):
		savepoint = f"lead_assignment_import_{index}"
		frappe.db.savepoint(savepoint)
		item = None
		try:
			lead = _create_batch_import_lead(row, actor_context)
			item = batch.append(
				"items",
				{
					"lead": lead.name,
					"status": "pending",
					"ownership_revision": int(lead.get("ownership_revision") or 0),
				},
			)
			item.reason = "Đã nhận trong đợt"
			created.append({"row": index, "lead": lead.name})
		except Exception as exc:
			frappe.db.rollback(save_point=savepoint)
			if item is not None:
				batch.items = [row_item for row_item in batch.items if row_item is not item]
			errors.append(
				{
					"row": index,
					"code": getattr(exc, "code", None) or "IMPORT_ROW_FAILED",
					"message": str(exc),
				}
			)
	_save_batch(batch)
	frappe.db.commit()
	result = _serialize_batch(batch)
	result["import"] = {
		"filename": (filename or "").strip(),
		"total": len(parsed_rows),
		"created": len(created),
		"failed": len(errors),
		"errors": errors,
	}
	return result


@frappe.whitelist(methods=["POST"])
def preview_lead_assignment_batch(batch_name: str):
	actor_context = _require_access()
	batch = frappe.get_doc(BATCH_DOCTYPE, batch_name)
	if batch.status in {"running", "completed", "cancelled"}:
		frappe.throw(_("Đợt này không còn cho phép kiểm tra trước."), frappe.ValidationError)
	_preview_batch_items(batch, actor_context)
	_save_batch(batch)
	frappe.db.commit()
	return _serialize_batch(batch)


def _assign_input_pool(batch, item, lead, actor_context: dict[str, Any]):
	if lead.get("owning_pool"):
		return int(lead.get("ownership_revision") or 0)
	pool = _resolve_batch_pool(batch, lead, actor_context)
	if lead.get("owning_team") and lead.get("owning_team") != pool.team:
		raise frappe.ValidationError("INPUT_QUEUE_TEAM_MISMATCH")
	result = change_student_ownership(
		student=lead.name,
		target_kind="pool",
		target_id=pool.name,
		target_team_id=pool.team,
		reason="Gán Lead vào hàng chờ của đợt trước khi phân công.",
		idempotency_key=f"lead-batch-pool:{batch.name}:{item.name}:{lead.get('ownership_revision') or 0}",
		expected_revision=int(lead.get("ownership_revision") or 0),
		correlation_id=batch.execution_id or str(uuid.uuid4()),
		_internal_service=True,
		_internal_actor=getattr(frappe.session, "user", None),
		_commit=False,
		_route_trigger="pool_entry",
		_enqueue_routing=False,
	)
	return int(result.get("revision") or 0)


def _apply_result(item, result: dict[str, Any], execution_id: str):
	ownership = result.get("ownership") or {}
	item.execution_id = execution_id
	item.routing_tier = result.get("tier") or item.routing_tier
	item.queue = result.get("queue") or item.queue
	item.owner_staff = result.get("owner_staff")
	item.team = result.get("owning_team") or item.team
	item.policy_version = (
		result.get("routing_policy_version")
		or result.get("policy_version")
		or ownership.get("routing_policy_version")
		or ownership.get("policy_version")
	)
	item.routing_request = result.get("request")
	if result.get("status") == "applied":
		item.status = "assigned"
		item.reason = f"{item.reason or 'ready'} → ASSIGNED"
		item.completed_at = now_datetime()
	elif result.get("status") in {"queued", "deferred"}:
		item.status = "deferred"
		item.reason = result.get("reason") or result.get("queue") or "DEFERRED"
		item.error_code = result.get("reason")
	else:
		item.status = "failed"
		item.reason = result.get("reason") or "ROUTING_FAILED"
		item.error_code = result.get("error_code") or result.get("reason") or "ROUTING_FAILED"


def _capacity_snapshot(staff: str | None) -> dict[str, int | None]:
	if not staff:
		return {"active": None, "limit": None, "remaining": None}
	period = frappe.db.get_value(
		"CRM Staff Capacity Period",
		{
			"staff": staff,
			"period_start": ["<=", getdate(today())],
			"period_end": [">=", getdate(today())],
			"approved": 1,
		},
		["max_active_students"],
		as_dict=True,
	)
	limit = int((period or {}).get("max_active_students") or 0)
	active = active_lead_count(staff)
	return {"active": active, "limit": limit or None, "remaining": max(0, limit - active) if limit else None}


@frappe.whitelist(methods=["POST"])
def run_lead_assignment_batch(batch_name: str):
	actor_context = _require_access()
	batch = frappe.get_doc(BATCH_DOCTYPE, batch_name)
	if batch.status not in RUNNABLE_STATUSES:
		frappe.throw(_("Đợt phải ở trạng thái Nháp, Sẵn sàng hoặc Có lỗi."), frappe.ValidationError)
	# Re-check topology immediately before execution. A Group, Team or member
	# may have changed after the operator first previewed the batch.
	_preview_batch_items(batch, actor_context)
	batch.status = "running"
	batch.execution_id = f"lead-batch-{uuid.uuid4().hex}"
	batch.started_at = now_datetime()
	batch.completed_at = None
	_save_batch(batch)

	# Capacity is measured from open assigned Leads. Without an in-run tally each
	# item would see the same load and the whole batch would land on one Sale,
	# contradicting the rotation the preview already showed the operator.
	load_overrides: dict[str, int] = {}
	for index, item in enumerate(batch.items):
		if item.status in TERMINAL_ITEM_STATUSES:
			continue
		savepoint = f"lead_assignment_{index}"
		frappe.db.savepoint(savepoint)
		try:
			lead = _batch_item_lead(item)
			processing_status = str(lead.get("processing_status") or "NEW").upper()
			if processing_status == "ASSIGNED":
				if (
					lead.get("converted_student")
					or str(lead.get("conversion_status") or "").casefold() == "converted"
				):
					_reset_item(item, status="skipped", reason="ALREADY_CONVERTED")
					item.execution_id = batch.execution_id
					item.completed_at = now_datetime()
					_persist_item(item)
					continue
				item.status = "assigned"
				item.reason = item.reason or "Đã phân công; chưa tạo hồ sơ Student."
				item.execution_id = batch.execution_id
				item.completed_at = now_datetime()
				_persist_item(item)
				continue
			if processing_status in {"NEW", "PROCESSING"}:
				# Intake processing is its own operator step ("Xử lý Lead"). A batch
				# run assigns what has already been processed and never advances
				# intake state on the operator's behalf.
				_reset_item(item, status="manual_review", reason="NOT_PROCESSED")
				item.error_code = "NOT_PROCESSED"
				item.execution_id = batch.execution_id
				item.completed_at = now_datetime()
				_save_batch(batch)
				continue
			if processing_status == "CLOSED":
				_reset_item(
					item,
					status="manual_review",
					reason=lead.get("resolution_reason") or "Hồ sơ đã đóng.",
				)
				item.error_code = "CLOSED"
				item.execution_id = batch.execution_id
				item.completed_at = now_datetime()
				_save_batch(batch)
				continue
			if processing_status != "PROCESSED":
				_reset_item(item, status="manual_review", reason="INVALID_PROCESSING_STATUS")
				item.error_code = "INVALID_PROCESSING_STATUS"
				item.execution_id = batch.execution_id
				item.completed_at = now_datetime()
				_save_batch(batch)
				continue
			if lead.get("owner_staff") or lead.get("assigned_to"):
				_reset_item(item, status="skipped", reason="ALREADY_ASSIGNED")
			else:
				recipient = _resolve_batch_recipient(
					batch, lead, actor_context, load_overrides=load_overrides
				)
				assignment = assign_lead(
					lead.name,
					recipient["ownerStaff"],
					recipient["team"],
					recipient["reason"],
					idempotency_key=f"lead-batch-owner:{batch.name}:{item.name}:{lead.get('ownership_revision') or 0}",
					expected_revision=int(lead.get("ownership_revision") or 0),
					correlation_id=f"{batch.execution_id}:{item.name}",
				)
				load_overrides[recipient["ownerStaff"]] = load_overrides.get(recipient["ownerStaff"], 0) + 1
				result = {
					"status": "applied",
					"owner_staff": recipient["ownerStaff"],
					"owning_team": recipient["team"],
					"reason": recipient["reason"],
					"policy_version": recipient["policyVersion"],
					"revision": assignment.get("ownership", {}).get("revision"),
					"ownership": assignment.get("ownership") or {},
				}
				_apply_result(item, result, batch.execution_id)
				item.ownership_revision = int(result.get("revision") or lead.get("ownership_revision") or 0)
				item.active_load = int(recipient["capacity"].get("active") or 0)
				item.capacity_limit = int(recipient["capacity"].get("limit") or 0)
				item.remaining_capacity = int(recipient["capacity"].get("remaining") or 0)
				_persist_item(item)
				item.status = "assigned"
				item.reason = item.reason or "Đã phân công; chưa tạo hồ sơ Student."
				item.completed_at = now_datetime()
				_persist_item(item)
		except Exception as exc:
			try:
				frappe.db.rollback(save_point=savepoint)
			except Exception:
				# assign_lead protects its own command transaction and may roll back
				# the database transaction, which also removes this savepoint.
				pass
			batch.reload()
			item = next(row for row in batch.items if row.name == item.name)
			code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
			if not code and str(exc).strip() in ROUTING_REVIEW_CODES:
				code = str(exc).strip()
			code = code or "ROUTING_FAILED"
			if code in PERMANENT_ASSIGNMENT_ERROR_CODES:
				_close_invalid_assignment_lead(item.lead, f"Lead bị đóng: {exc}")
			item.status = (
				"failed"
				if code in PERMANENT_ASSIGNMENT_ERROR_CODES
				else "manual_review"
				if code in ROUTING_REVIEW_CODES
				else "failed"
			)
			item.reason = str(exc)
			item.error_code = code
			item.execution_id = batch.execution_id
			item.completed_at = now_datetime()
		batch.status = "running"
		_save_batch(batch)

	# Reload the child table after per-item ownership commits so the final
	# summary/history is calculated from the persisted audit rows.
	batch.reload()
	batch.completed_at = now_datetime()
	_count_items(batch)
	batch.status = (
		"completed"
		if not any(item.status in {"deferred", "manual_review", "failed"} for item in batch.items)
		else "completed_with_errors"
	)
	_save_batch(batch)
	frappe.db.commit()
	return _serialize_batch(batch)


def _unassigned_lead_names(actor_context: dict[str, Any]) -> list[str]:
	"""Return visible, processed Leads that still have no owner.

	Lead source is not part of the selection rule because another system owns
	intake. Processing state is, because "Xử lý Lead" is the operator step that
	decides which Leads are assignable at all.
	"""
	rows = frappe.get_all(
		"CRM Lead",
		filters={
			"processing_status": "PROCESSED",
		},
		fields=["name", "owner_staff", "assigned_to", "converted_student", "conversion_status"],
		order_by="creation asc, name asc",
		limit_page_length=MAX_BATCH_SIZE,
	)
	lead_names = []
	for row in rows:
		if row.get("owner_staff") or row.get("assigned_to") or row.get("converted_student"):
			continue
		if str(row.get("conversion_status") or "").casefold() == "converted":
			continue
		# get_all is intentionally used for the candidate scan, but each Lead is
		# still checked through the normal row permission boundary before use.
		try:
			_lead(row.get("name"))
		except frappe.PermissionError:
			continue
		lead_names.append(row.get("name"))
	return [name for name in lead_names if name]


def _new_unassigned_lead_batch(lead_names: list[str]):
	"""Create an internal audit batch for one manual scan."""
	stamp = now_datetime().strftime("%Y%m%d-%H%M%S")
	batch_name = f"Phân công Lead {stamp}"
	if frappe.db.exists(BATCH_DOCTYPE, {"batch_name": batch_name}):
		batch_name = f"{batch_name}-{uuid.uuid4().hex[:6]}"
	batch = frappe.get_doc(
		{
			"doctype": BATCH_DOCTYPE,
			"batch_name": batch_name,
			"status": "draft",
			"source": "system-unassigned-leads",
			"description": "Hệ thống quét Lead chưa được phân công và chạy theo cấu hình hiện tại.",
			"created_by": frappe.session.user,
		}
	)
	for lead_name in lead_names:
		lead = _lead(lead_name)
		batch.append(
			"items",
			{
				"lead": lead.name,
				"status": "pending",
				"ownership_revision": int(lead.get("ownership_revision") or 0),
			},
		)
	_save_batch(batch)
	frappe.db.commit()
	return batch


@frappe.whitelist(methods=["POST"])
def run_unassigned_lead_assignment():
	"""Scan and assign every processed CRM Lead that does not have an owner.

	This is the simple operator action used by dashboard-crm. Leads still in
	NEW must first go through "Xử lý Lead" (``process_new_leads``); this command
	never advances intake state itself.
	"""
	actor_context = _require_access()
	lead_names = _unassigned_lead_names(actor_context)
	if not lead_names:
		return {
			"status": "no_work",
			"message": "Không có Lead đã xử lý nào đang chờ phân công.",
			"scanned": 0,
			"batch": None,
			"items": [],
			"summary": {
				"total": 0,
				"valid": 0,
				"invalid": 0,
				"pending": 0,
				"assigned": 0,
				"deferred": 0,
				"manualReview": 0,
				"failed": 0,
				"skipped": 0,
			},
		}

	batch = _new_unassigned_lead_batch(lead_names)
	result = run_lead_assignment_batch(batch.name)
	result["scanned"] = len(lead_names)
	result["trigger"] = "unassigned_leads"
	return result


@frappe.whitelist(methods=["POST"])
def retry_lead_assignment_batch(batch_name: str, item_ids: list[str] | str | None = None):
	_require_access()
	batch = frappe.get_doc(BATCH_DOCTYPE, batch_name)
	selected = set(_parse_list(item_ids, "item_ids")) if item_ids else None
	for item in batch.items:
		if selected is not None and item.name not in selected:
			continue
		if _retryable_item(item):
			_reset_item(item)
	batch.status = "ready"
	_save_batch(batch)
	frappe.db.commit()
	return run_lead_assignment_batch(batch.name)


@frappe.whitelist()
def get_lead_assignment_batch(batch_name: str):
	actor_context = _require_read_access()
	batch = frappe.get_doc(BATCH_DOCTYPE, batch_name)
	if batch.pool:
		_pool(batch.pool, None, actor_context)
	return _serialize_batch(batch)


@frappe.whitelist()
def get_lead_assignment_workflow(batch_name: str | None = None):
	"""Return live Lead state or the selected batch's audit projection."""
	actor_context = _require_read_access()
	if batch_name:
		batch = frappe.get_doc(BATCH_DOCTYPE, batch_name)
		if batch.pool:
			_pool(batch.pool, None, actor_context)
		return _serialize_assignment_workflow(batch)

	return _serialize_assignment_workflow(summary=_processing_workflow_summary())


@frappe.whitelist()
def list_lead_assignment_batches(
	limit: int | str = 50,
	page: int | str = 1,
	page_size: int | str | None = None,
	status: str | None = None,
	q: str | None = None,
):
	actor_context = _require_read_access()
	try:
		requested_page_size = page_size if page_size not in (None, "") else limit
		page_size = max(1, min(int(requested_page_size), 100))
		page = max(1, int(page or 1))
	except (TypeError, ValueError):
		frappe.throw(_("Thông tin phân trang không hợp lệ."), frappe.ValidationError)
	filters = {}
	if status and status != "all":
		if status not in {"draft", "ready", "running", "completed", "completed_with_errors", "cancelled"}:
			frappe.throw(_("Trạng thái đợt không hợp lệ."), frappe.ValidationError)
		filters["status"] = status
	search = str(q or "").strip()
	if len(search) > 140:
		frappe.throw(_("Từ khóa tìm kiếm quá dài."), frappe.ValidationError)
	if search:
		filters["batch_name"] = ["like", f"%{search}%"]
	if not actor_context.get("is_system_manager"):
		allowed_teams = actor_context.get("teams") or ["__no_team__"]
		team_province_rows = frappe.get_all(
			"CRM Team",
			filters={"name": ["in", allowed_teams], "is_active": 1},
			fields=["group"],
			limit_page_length=0,
		)
		allowed_group_ids = [row.group for row in team_province_rows if row.group]
		allowed_provinces = frappe.get_all(
			"CRM Team Group",
			filters={"name": ["in", allowed_group_ids or ["__no_group__"]], "is_active": 1},
			pluck="province",
			limit_page_length=200,
		)
		or_filters = [
			{"province": ["in", allowed_provinces or ["__no_province__"]]},
			{"target_team": ["in", allowed_teams]},
			{"created_by": actor_context["actor"]},
		]
	else:
		or_filters = None
	fields = [
		"name",
		"batch_name",
		"status",
		"province",
		"target_team",
		"pool",
		"source",
		"total_count",
		"assigned_count",
		"deferred_count",
		"manual_review_count",
		"failed_count",
		"created_by",
		"creation",
	]
	query = {
		"doctype": BATCH_DOCTYPE,
		"filters": filters,
		"fields": fields,
		"order_by": "creation desc",
		"limit_page_length": page_size,
		"limit_start": (page - 1) * page_size,
	}
	if or_filters:
		query["or_filters"] = or_filters
	total = len(
		frappe.get_all(
			BATCH_DOCTYPE,
			filters=filters,
			or_filters=or_filters,
			fields=["name"],
			limit_page_length=0,
		)
	)
	total_pages = max(1, (total + page_size - 1) // page_size)
	return {
		"items": frappe.get_all(**query),
		"pagination": {
			"page": page,
			"page_size": page_size,
			"total": total,
			"total_pages": total_pages,
			"has_next_page": page < total_pages,
		},
	}


@frappe.whitelist()
def list_lead_assignment_history_items(
	limit: int | str = 50,
	page: int | str = 1,
	status: str | None = None,
	q: str | None = None,
	lead_ids: list[str] | str | None = None,
):
	"""Return batch history plus currently closed Leads that need operator review."""
	try:
		page_size = max(1, min(int(limit), 100))
		page_number = max(1, int(page or 1))
	except (TypeError, ValueError):
		frappe.throw(_("Thông tin phân trang không hợp lệ."), frappe.ValidationError)
	allowed_statuses = {"pending", "assigned", "deferred", "manual_review", "failed", "skipped"}
	if status and status != "all" and status not in allowed_statuses:
		frappe.throw(_("Trạng thái hồ sơ không hợp lệ."), frappe.ValidationError)
	search = str(q or "").strip().casefold()
	if len(search) > 140:
		frappe.throw(_("Từ khóa tìm kiếm quá dài."), frappe.ValidationError)
	selected_lead_ids = set(_parse_list(lead_ids, "lead_ids")) if lead_ids else None
	batches = []
	batch_page = 1
	while True:
		batch_response = list_lead_assignment_batches(limit=100, page=batch_page)
		batches.extend(batch_response.get("items", []))
		if not batch_response.get("pagination", {}).get("has_next_page"):
			break
		batch_page += 1
	items = []
	seen_lead_ids: set[str] = set()

	def include_item(serialized: dict[str, Any]) -> None:
		lead_id = str(serialized.get("leadId") or "")
		if selected_lead_ids is not None and lead_id not in selected_lead_ids:
			return
		if status and status != "all" and serialized["status"] != status:
			return
		if search:
			searchable = " ".join(
				str(serialized.get(field) or "")
				for field in (
					"studentName",
					"leadId",
					"phone",
					"province",
					"team",
					"ownerStaff",
					"reason",
				)
			).casefold()
			if search not in searchable:
				return
		items.append(serialized)

	for batch_row in batches:
		batch = frappe.get_doc(BATCH_DOCTYPE, batch_row["name"])
		for item in batch.items:
			serialized = _serialize_item(item)
			serialized.update(
				{
					"batchId": batch.name,
					"batchCreatedAt": str(batch.creation) if batch.creation else None,
					"batchStatus": batch.status,
				}
			)
			seen_lead_ids.add(str(serialized.get("leadId") or ""))
			include_item(serialized)
	for lead in _live_closed_leads(selected_lead_ids):
		if lead.name in seen_lead_ids:
			continue
		include_item(_serialize_live_review_item(lead))
	items.sort(key=lambda row: (row.get("batchCreatedAt") or "", row.get("id") or ""), reverse=True)
	total = len(items)
	start = (page_number - 1) * page_size
	page_items = items[start : start + page_size]
	total_pages = max(1, (total + page_size - 1) // page_size)
	return {
		"items": page_items,
		"pagination": {
			"page": page_number,
			"page_size": page_size,
			"total": total,
			"total_pages": total_pages,
			"has_next_page": page_number < total_pages,
		},
	}


@frappe.whitelist()
def get_lead_assignment_batch_options():
	"""Return province choices; Team/Pool are legacy compatibility fields only.

	New dashboard flows choose no queue and no Team.  The batch router resolves
	all active Teams under the Lead's Province Group automatically.
	"""
	actor_context = _require_read_access()
	team_filters = {"is_active": 1, "team_type": "Sales"}
	if not actor_context.get("is_system_manager"):
		team_filters["name"] = ["in", actor_context.get("teams") or ["__no_team__"]]
	teams = frappe.get_list(
		"CRM Team",
		filters=team_filters,
		fields=["name", "team_name", "group", "campus"],
		order_by="team_name asc, name asc",
		limit_page_length=200,
	)
	for team in teams:
		team["province"] = (
			frappe.db.get_value("CRM Team Group", team.get("group"), "province")
			if team.get("group")
			else None
		)
	province_filters = {}
	if not actor_context.get("is_system_manager"):
		allowed_provinces = {team.get("province") for team in teams if team.get("province")}
		province_filters = {"name": ["in", sorted(allowed_provinces) or ["__no_province__"]]}
	return {
		"provinces": frappe.get_list(
			"CRM Province",
			filters=province_filters,
			fields=["name", "province_name", "province_code"],
			order_by="province_name asc, name asc",
			limit_page_length=200,
		),
		"teams": teams,
		"pools": frappe.get_list(
			"CRM Student Pool",
			filters={"is_active": 1},
			fields=["name", "pool_name", "team", "campus"],
			order_by="pool_name asc",
			limit_page_length=200,
		),
	}


def _catalog_rows(doctype: str, fields: list[str], label_field: str, filters=None):
	rows = frappe.get_list(
		doctype,
		filters=filters or {},
		fields=fields,
		order_by=f"{label_field} asc, name asc",
		limit_page_length=5000,
	)
	return [
		{
			"id": row.get("name"),
			"label": row.get(label_field) or row.get("name"),
			"code": row.get("province_code")
			or row.get("school_code")
			or row.get("major_code")
			or row.get("campus_code"),
		}
		for row in rows
	]


@frappe.whitelist(methods=["GET"])
def get_lead_assignment_catalogs(province: str | None = None):
	"""Return Frappe-owned choices for the batch Lead form."""
	_require_read_access()
	province_name = str(province or "").strip()
	if province_name and not frappe.db.exists("CRM Province", province_name):
		province_name = lead_mapping._resolve_province(province_name)
	return {
		"provinces": _catalog_rows(
			"CRM Province",
			["name", "province_name", "province_code"],
			"province_name",
		),
		"sources": _catalog_rows(
			"CRM Lead Source",
			["name", "source_name"],
			"source_name",
			{"approval_state": ["!=", "Retired"]},
		),
		"majors": _catalog_rows(
			"CRM Major",
			["name", "major_name", "major_code"],
			"major_name",
		),
		"branches": _catalog_rows(
			"CRM Campus",
			["name", "campus_name", "campus_code"],
			"campus_name",
			{"approval_state": ["!=", "Retired"]},
		),
		"highSchools": (
			_catalog_rows(
				"CRM High School",
				["name", "school_name", "school_code", "province"],
				"school_name",
				{"province": province_name},
			)
			if province_name
			else []
		),
	}
